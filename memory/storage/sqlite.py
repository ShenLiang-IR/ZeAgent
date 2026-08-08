import asyncio
import json
import os
from datetime import datetime
from contextlib import closing
from typing import Optional, List
from ..blocks import MemoryBlock


class SQLiteStorage:
    def __init__(self, db_path: str = "data/memory.db"):
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._ensure_db()
    def _ensure_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        import sqlite3
        with closing(sqlite3.connect(self._db_path, isolation_level=None)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    type TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    session_id TEXT,
                    user_id TEXT,
                    tags TEXT,
                    metadata TEXT
                )
            """)
            # 迁移：老库无 tier 列时补列（存量默认 'long_term'）
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
            if "tier" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN tier TEXT NOT NULL DEFAULT 'long_term'")
            if "workspace_id" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN workspace_id TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_content ON memories(content)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user_session ON memories(user_id, session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tier ON memories(tier)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_workspace ON memories(workspace_id)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_audit (
                    op_id TEXT PRIMARY KEY,
                    op_type TEXT,
                    workspace_id TEXT,
                    user_id TEXT,
                    kept_id TEXT,
                    kept_content_before TEXT,
                    deleted_snapshot TEXT,
                    merged_content TEXT,
                    reason TEXT,
                    created_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON memory_audit(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_workspace ON memory_audit(workspace_id)")
    async def save(self, memory: MemoryBlock, tier: str = "long_term") -> bool:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO memories (id, content, type, importance, created_at, last_accessed, access_count, session_id, user_id, tags, metadata, tier, workspace_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (memory.id, memory.content,
                     memory.type.value if hasattr(memory.type, 'value') else str(memory.type),
                     memory.importance,
                     memory.created_at.isoformat(), memory.last_accessed.isoformat(),
                     memory.access_count, memory.session_id, memory.user_id,
                     json.dumps(memory.tags), json.dumps(memory.metadata), tier,
                     memory.workspace_id)
                )
                return True
    async def load(self, memory_id: str) -> Optional[MemoryBlock]:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                cur = await db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
                row = await cur.fetchone()
                await cur.close()
                return self._row_to_memory(row) if row else None
    async def delete(self, memory_id: str) -> bool:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                cur = await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                rowcount = cur.rowcount
                await cur.close()
                return rowcount > 0
    async def search(self, query: str, limit: int = 10, tier: Optional[str] = None,
                     workspace_id: Optional[str] = None) -> List[MemoryBlock]:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                # 动态拼接 WHERE：tier / workspace_id 可选过滤
                where = ["content LIKE ?"]
                params: list = [f"%{query}%"]
                if tier:
                    where.append("tier = ?")
                    params.append(tier)
                if workspace_id:
                    where.append("workspace_id = ?")
                    params.append(workspace_id)
                params.append(limit)
                cur = await db.execute(
                    f"SELECT * FROM memories WHERE {' AND '.join(where)} ORDER BY importance DESC, last_accessed DESC LIMIT ?",
                    params
                )
                rows = await cur.fetchall()
                await cur.close()
                return [self._row_to_memory(row) for row in rows]
    async def list_all(self, limit: int = 100, offset: int = 0, tier: Optional[str] = None) -> List[MemoryBlock]:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                if tier:
                    cur = await db.execute(
                        "SELECT * FROM memories WHERE tier = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                        (tier, limit, offset)
                    )
                else:
                    cur = await db.execute(
                        "SELECT * FROM memories ORDER BY created_at DESC LIMIT ? OFFSET ?",
                        (limit, offset)
                    )
                rows = await cur.fetchall()
                await cur.close()
                return [self._row_to_memory(row) for row in rows]
    async def list_by_tier(self, tier: str, limit: int = 10000, offset: int = 0) -> List[MemoryBlock]:
        return await self.list_all(limit=limit, offset=offset, tier=tier)
    async def list_recent_by_user(self, tier: str, user_id: Optional[str] = None,
                                  workspace_id: Optional[str] = None,
                                  limit: int = 1000) -> List[MemoryBlock]:
        """按 created_at 倒序 + user/workspace 预过滤（SQL 层，避免 get_all 全量加载）。"""
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                where = ["tier = ?"]
                params: list = [tier]
                if user_id:
                    where.append("user_id = ?")
                    params.append(user_id)
                if workspace_id:
                    where.append("workspace_id = ?")
                    params.append(workspace_id)
                params.append(limit)
                cur = await db.execute(
                    f"SELECT * FROM memories WHERE {' AND '.join(where)} "
                    f"ORDER BY created_at DESC LIMIT ?",
                    params
                )
                rows = await cur.fetchall()
                await cur.close()
                return [self._row_to_memory(row) for row in rows]
    async def delete_by_tier(self, tier: str) -> int:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                cur = await db.execute("DELETE FROM memories WHERE tier = ?", (tier,))
                rowcount = cur.rowcount
                await cur.close()
                return rowcount
    async def count_by_tier(self, tier: str) -> int:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                cur = await db.execute("SELECT COUNT(*) FROM memories WHERE tier = ?", (tier,))
                row = await cur.fetchone()
                await cur.close()
                return row[0] if row else 0
    async def delete_by_session_and_tier(self, session_id: str, tier: str) -> int:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                cur = await db.execute("DELETE FROM memories WHERE tier = ? AND session_id = ?", (tier, session_id))
                rowcount = cur.rowcount
                await cur.close()
                return rowcount
    async def delete_by_user_and_tier(self, user_id: str, tier: str) -> int:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                cur = await db.execute("DELETE FROM memories WHERE tier = ? AND user_id = ?", (tier, user_id))
                rowcount = cur.rowcount
                await cur.close()
                return rowcount
    async def clear(self) -> bool:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                await db.execute("DELETE FROM memories")
                return True
    async def count(self) -> int:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                cur = await db.execute("SELECT COUNT(*) FROM memories")
                row = await cur.fetchone()
                await cur.close()
                return row[0] if row else 0
    def _row_to_memory(self, row) -> MemoryBlock:
        return MemoryBlock(
            id=row[0],
            content=row[1],
            type=row[2],
            importance=row[3],
            created_at=datetime.fromisoformat(row[4]),
            last_accessed=datetime.fromisoformat(row[5]),
            access_count=row[6],
            session_id=row[7],
            user_id=row[8],
            tags=json.loads(row[9]) if row[9] else [],
            metadata=json.loads(row[10]) if row[10] else {},
            workspace_id=row[12] if len(row) > 12 else None,
        )
    # ─── 破坏性合并审计 ───
    async def save_audit(self, audit: dict) -> bool:
        import aiosqlite, uuid
        op_id = audit.get("op_id") or str(uuid.uuid4())
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO memory_audit "
                    "(op_id, op_type, workspace_id, user_id, kept_id, kept_content_before, "
                    "deleted_snapshot, merged_content, reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (op_id, audit.get("op_type"), audit.get("workspace_id"),
                     audit.get("user_id"), audit.get("kept_id"),
                     audit.get("kept_content_before"),
                     json.dumps(audit.get("deleted_snapshot"), ensure_ascii=False) if audit.get("deleted_snapshot") is not None else None,
                     audit.get("merged_content"), audit.get("reason"),
                     audit.get("created_at") or datetime.now().isoformat())
                )
                return True
    async def get_audit(self, op_id: str) -> Optional[dict]:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                cur = await db.execute(
                    "SELECT op_id, op_type, workspace_id, user_id, kept_id, "
                    "kept_content_before, deleted_snapshot, merged_content, reason, created_at "
                    "FROM memory_audit WHERE op_id = ?", (op_id,)
                )
                row = await cur.fetchone()
                await cur.close()
                if not row:
                    return None
                return {
                    "op_id": row[0], "op_type": row[1], "workspace_id": row[2],
                    "user_id": row[3], "kept_id": row[4],
                    "kept_content_before": row[5],
                    "deleted_snapshot": json.loads(row[6]) if row[6] else None,
                    "merged_content": row[7], "reason": row[8], "created_at": row[9],
                }
    async def list_audit(self, workspace_id: Optional[str] = None,
                         user_id: Optional[str] = None,
                         limit: int = 50, offset: int = 0) -> List[dict]:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                where = []
                params: list = []
                if workspace_id:
                    where.append("workspace_id = ?")
                    params.append(workspace_id)
                if user_id:
                    where.append("user_id = ?")
                    params.append(user_id)
                where_clause = f"WHERE {' AND '.join(where)}" if where else ""
                params.extend([limit, offset])
                cur = await db.execute(
                    f"SELECT op_id, op_type, workspace_id, user_id, kept_id, "
                    f"kept_content_before, deleted_snapshot, merged_content, reason, created_at "
                    f"FROM memory_audit {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    params
                )
                rows = await cur.fetchall()
                await cur.close()
                return [
                    {"op_id": r[0], "op_type": r[1], "workspace_id": r[2], "user_id": r[3],
                     "kept_id": r[4], "kept_content_before": r[5],
                     "deleted_snapshot": json.loads(r[6]) if r[6] else None,
                     "merged_content": r[7], "reason": r[8], "created_at": r[9]}
                    for r in rows
                ]
    async def delete_audit(self, op_id: str) -> bool:
        import aiosqlite
        async with self._lock:
            async with aiosqlite.connect(self._db_path, isolation_level=None) as db:
                cur = await db.execute("DELETE FROM memory_audit WHERE op_id = ?", (op_id,))
                rowcount = cur.rowcount
                await cur.close()
                return rowcount > 0
