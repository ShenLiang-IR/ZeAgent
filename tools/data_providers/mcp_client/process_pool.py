"""MCP stdio 进程池：复用连接，避免每次 tool call 都 fork+terminate。

核心设计：
- 按 pool_key（command+args+env 的哈希）维护长连接子进程
- 首次 acquire：启动进程 + initialize 握手；后续直接 tools/call
- 空闲 _IDLE_TIMEOUT 秒后自动回收（后台清理 task）
- 进程崩溃/出错时自动从池中移除，下次重新创建
- 全局 _MAX_POOL_SIZE 上限，超出时 LRU 驱逐最久未用的连接

资源预估（100 MCP）：
- 100 个 MCP 全部活跃 = 100 进程 ~5GB
- 进程池保活热连接 20 个 ~1GB
- 空闲 5 分钟后自动回收 → 常态 ~0 进程
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional
from loguru import logger


# ── 配置 ──
_IDLE_TIMEOUT = 300  # 空闲多少秒后回收进程
_MAX_POOL_SIZE = 20  # 全局最大保活进程数
_MAX_PER_KEY = 3     # 同一 MCP 最多 3 个并发进程


class McpConnection:
    """一个 MCP stdio 长连接（复用已握手的子进程）。"""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        pool_key: str,
        conn_id: int,
    ):
        self.process = process
        self.pool_key = pool_key
        self.conn_id = conn_id
        self.last_used = time.time()
        self._initialized = False
        self._lock = asyncio.Lock()  # 同一连接串行调用（stdio 是单工的）

    async def initialize(self) -> bool:
        """发 MCP initialize 握手 + initialized 通知。"""
        if self._initialized:
            return True
        try:
            init_req = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 0,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "InvRes-Agent", "version": "1.0.0"}
                }
            }
            self.process.stdin.write((json.dumps(init_req) + "\n").encode())
            await self.process.stdin.drain()
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=30.0)
            if line and line.strip():
                resp = json.loads(line.decode("utf-8", errors="ignore").strip())
                server_info = resp.get("result", {}).get("serverInfo", {})
                logger.debug(f"[McpPool] handshake OK: {server_info}")
            # 发 initialized 通知
            notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            self.process.stdin.write((json.dumps(notif) + "\n").encode())
            await self.process.stdin.drain()
            self._initialized = True
            return True
        except Exception as e:
            logger.warning(f"[McpPool] initialize failed (conn {self.conn_id}): {e}")
            return False

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: float = 60.0) -> str:
        """在已握手的连接上发 tools/call，返回文本结果。"""
        async with self._lock:
            self.last_used = time.time()
            req = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": 1,
                "params": {"name": tool_name, "arguments": arguments}
            }
            self.process.stdin.write((json.dumps(req) + "\n").encode())
            await self.process.stdin.drain()
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=timeout)
            if not line or not line.strip():
                stderr = await self._read_stderr()
                raise RuntimeError(f"MCP 空响应 (stderr: {stderr[:200]})")
            result = json.loads(line.decode("utf-8", errors="ignore").strip())
            if "error" in result:
                raise RuntimeError(f"MCP 错误: {result['error']}")
            content = result.get("result", {}).get("content", [])
            return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")

    async def list_tools(self, timeout: float = 30.0) -> List[Dict[str, Any]]:
        """在已握手的连接上发 tools/list，返回工具列表。"""
        async with self._lock:
            self.last_used = time.time()
            req = {"jsonrpc": "2.0", "method": "tools/list", "id": 2}
            self.process.stdin.write((json.dumps(req) + "\n").encode())
            await self.process.stdin.drain()
            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=timeout)
            if not line or not line.strip():
                raise RuntimeError("MCP tools/list 空响应")
            result = json.loads(line.decode("utf-8", errors="ignore").strip())
            if "error" in result:
                raise RuntimeError(f"MCP 错误: {result['error']}")
            return result.get("result", {}).get("tools", [])

    async def _read_stderr(self) -> str:
        try:
            data = await asyncio.wait_for(self.process.stderr.read(1024), timeout=0.5)
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def is_alive(self) -> bool:
        return self.process.returncode is None

    async def close(self) -> None:
        """终止子进程。"""
        try:
            if self.process.returncode is None:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except Exception:
            try:
                if self.process.returncode is None:
                    self.process.kill()
            except Exception:
                pass


class McpProcessPool:
    """MCP stdio 进程池：按 pool_key 管理连接，惰性创建 + 空闲回收。"""

    _instance: Optional["McpProcessPool"] = None

    def __init__(self):
        self._pools: OrderedDict[str, List[McpConnection]] = OrderedDict()
        self._conn_counter = 0
        self._cleanup_task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "McpProcessPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def make_pool_key(command: str, args: List[str], env: Optional[Dict[str, str]] = None) -> str:
        """生成 pool key（command+args+env 的 MD5）。"""
        raw = f"{command}|{','.join(args)}|{json.dumps(env or {}, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    async def acquire(
        self,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> McpConnection:
        """获取一个连接：优先复用池中空闲的，没有则创建新的。"""
        pool_key = self.make_pool_key(command, args, env)

        # 1. 尝试复用已有的空闲连接
        conns = self._pools.get(pool_key, [])
        for conn in conns:
            if conn.is_alive() and not conn._lock.locked():
                logger.debug(f"[McpPool] reuse conn {conn.conn_id} for {pool_key}")
                self._touch(pool_key)
                return conn

        # 2. 池满驱逐
        self._evict_if_full()

        # 3. 创建新进程
        conn = await self._create_connection(command, args, env, pool_key, timeout)
        return conn

    async def _create_connection(
        self,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]],
        pool_key: str,
        timeout: float,
    ) -> McpConnection:
        """创建新进程 + 握手 + 加入池（应用沙箱策略）。"""
        full_env = os.environ.copy()
        if env:
            from utils.mcp_util import resolve_env_vars
            full_env.update(resolve_env_vars(env))

        # 注入沙箱环境变量
        full_env["SANDBOX_ROOT"] = ""
        full_env["SANDBOX_SKILL_ID"] = f"mcp_{pool_key}"
        full_env["SANDBOX_TIMEOUT"] = str(int(timeout))

        # Linux 资源限制
        preexec = None
        if platform.system() == "Linux":
            def preexec():
                try:
                    import resource
                    mem_bytes = 512 * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
                    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
                    fsize_bytes = 100 * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
                except Exception:
                    pass

        process = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
            preexec_fn=preexec,
        )
        self._conn_counter += 1
        conn = McpConnection(process, pool_key, self._conn_counter)

        # 握手
        ok = await conn.initialize()
        if not ok:
            await conn.close()
            raise RuntimeError(f"MCP 进程握手失败: {command} {' '.join(args)}")

        # 加入池
        conns = self._pools.setdefault(pool_key, [])
        if len(conns) >= _MAX_PER_KEY:
            # 同一 key 超上限，关掉最旧的
            old = conns.pop(0)
            await old.close()
        conns.append(conn)
        self._touch(pool_key)
        self._start_cleanup_if_needed()
        logger.info(f"[McpPool] created conn {conn.conn_id} for {pool_key} (pool size={self._total_size()})")
        return conn

    async def call_tool(
        self,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]],
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float = 60.0,
    ) -> str:
        """便捷方法：acquire → call_tool →（不归还，连接留在池中复用）。含审计日志。"""
        from infrastructure.sandbox.policy import ExecutionAuditLog
        import time as _time

        pool_key = self.make_pool_key(command, args, env)
        start = _time.perf_counter()
        conn = await self.acquire(command, args, env)
        try:
            result = await conn.call_tool(tool_name, arguments, timeout)
            duration_ms = (_time.perf_counter() - start) * 1000
            ExecutionAuditLog.log(
                skill_id=f"mcp_{pool_key}",
                plugin_type="mcp_server",
                caller="system",
                action=f"call_tool:{tool_name}",
                duration_ms=duration_ms,
                success=True,
            )
            return result
        except Exception as e:
            duration_ms = (_time.perf_counter() - start) * 1000
            ExecutionAuditLog.log(
                skill_id=f"mcp_{pool_key}",
                plugin_type="mcp_server",
                caller="system",
                action=f"call_tool:{tool_name}",
                duration_ms=duration_ms,
                success=False,
                error=str(e)[:200],
            )
            # 出错时把连接从池中移除（可能进程已崩）
            await self._remove_conn(conn)
            raise

    async def list_tools(
        self,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]],
        timeout: float = 30.0,
    ) -> List[Dict[str, Any]]:
        """便捷方法：acquire → list_tools。"""
        conn = await self.acquire(command, args, env)
        try:
            return await conn.list_tools(timeout)
        except Exception:
            await self._remove_conn(conn)
            raise

    def _touch(self, pool_key: str) -> None:
        """LRU：把 key 移到末尾（最近使用）。"""
        if pool_key in self._pools:
            self._pools.move_to_end(pool_key)

    def _total_size(self) -> int:
        return sum(len(v) for v in self._pools.values())

    def _evict_if_full(self) -> None:
        """全局超上限时驱逐最久未用的 key 的最旧连接。"""
        while self._total_size() >= _MAX_POOL_SIZE and self._pools:
            oldest_key = next(iter(self._pools))
            conns = self._pools[oldest_key]
            if conns:
                old = conns.pop(0)
                logger.debug(f"[McpPool] evict conn {old.conn_id} (pool full)")
                asyncio.get_event_loop().create_task(old.close())
            if not conns:
                del self._pools[oldest_key]

    async def _remove_conn(self, conn: McpConnection) -> None:
        """从池中移除并关闭指定连接。"""
        conns = self._pools.get(conn.pool_key, [])
        if conn in conns:
            conns.remove(conn)
        if not conns and conn.pool_key in self._pools:
            del self._pools[conn.pool_key]
        await conn.close()
        logger.debug(f"[McpPool] removed conn {conn.conn_id} (pool size={self._total_size()})")

    def _start_cleanup_if_needed(self) -> None:
        """启动后台空闲回收 task（如果还没启动）。"""
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                loop = asyncio.get_event_loop()
                self._cleanup_task = loop.create_task(self._idle_cleanup_loop())
            except RuntimeError:
                pass

    async def _idle_cleanup_loop(self) -> None:
        """每 60s 清理一次空闲超时的连接。"""
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                to_remove: list[McpConnection] = []
                for pool_key, conns in list(self._pools.items()):
                    alive = []
                    for conn in conns:
                        if not conn.is_alive() or (now - conn.last_used > _IDLE_TIMEOUT):
                            to_remove.append(conn)
                        else:
                            alive.append(conn)
                    if alive:
                        self._pools[pool_key] = alive
                    else:
                        self._pools.pop(pool_key, None)
                for conn in to_remove:
                    logger.debug(f"[McpPool] idle evict conn {conn.conn_id}")
                    await conn.close()
                if to_remove:
                    logger.info(f"[McpPool] cleaned {len(to_remove)} idle conns (pool size={self._total_size()})")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[McpPool] cleanup error: {e}")

    async def shutdown(self) -> None:
        """关闭所有连接（服务 shutdown 时调用）。"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        for pool_key, conns in list(self._pools.items()):
            for conn in conns:
                await conn.close()
        self._pools.clear()
        logger.info("[McpPool] all connections closed")


def reset_process_pool() -> None:
    """重置进程池单例（测试用）。"""
    if McpProcessPool._instance and McpProcessPool._instance._cleanup_task:
        if not McpProcessPool._instance._cleanup_task.done():
            McpProcessPool._instance._cleanup_task.cancel()
    McpProcessPool._instance = None
