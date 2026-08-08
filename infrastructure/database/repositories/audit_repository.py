"""审计日志 repository。

参照 trigger_repository.py 风格：BaseRepository[Model, Dict] + 业务方法。
"""
from typing import Any

from loguru import logger
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from infrastructure.database.models.audit import AuditLog
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class AuditRepository(BaseRepository[AuditLog, dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = AuditLog
    _pk_name = 'pr_key_id'
    _table_ensured = False

    def _ensure_table(self):
        """确保 tb_audit_log 表存在（幂等 lazy init）。

        审计日志表可能未建（model 定义了但 DB 无表），写日志前确保建表。
        """
        if AuditRepository._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            Base.metadata.create_all(get_config_engine(), tables=[AuditLog.__table__], checkfirst=True)
            AuditRepository._table_ensured = True
        except Exception as e:
            logger.warning(f"[AuditRepository] _ensure_table failed (non-fatal): {e}")

    def create(self, **kwargs):
        """建表 + 写审计日志（重写 BaseRepository.create，确保表存在）。"""
        self._ensure_table()
        return super().create(**kwargs)

    def _entity_to_dict(self, entity: AuditLog, session: Session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'audit_id': entity.audit_id,
            'user_id': entity.user_id,
            'username': entity.username,
            'workspace_id': entity.workspace_id,
            'http_method': entity.http_method,
            'path': entity.path,
            'resource_type': entity.resource_type,
            'resource_id': entity.resource_id,
            'action': entity.action,
            'before_data': entity.before_data,
            'after_data': entity.after_data,
            'client_ip': entity.client_ip,
            'user_agent': entity.user_agent,
            'status_code': entity.status_code,
            'duration_ms': entity.duration_ms,
            'error': entity.error,
            'create_time': str(entity.create_time) if entity.create_time else None,
        }

    def list_by_user(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """按 user_id 查询审计历史。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(AuditLog)
                    .where(AuditLog.user_id == user_id)
                    .order_by(AuditLog.pr_key_id.desc())
                    .limit(limit)
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"AuditRepository.list_by_user ({user_id}): {e}", exc_info=True)
            return []

    def list_by_resource(self, resource_type: str, resource_id: str,
                         limit: int = 50) -> list[dict[str, Any]]:
        """按 resource_type + resource_id 查询审计历史。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(AuditLog)
                    .where(and_(
                        AuditLog.resource_type == resource_type,
                        AuditLog.resource_id == resource_id,
                    ))
                    .order_by(AuditLog.pr_key_id.desc())
                    .limit(limit)
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"AuditRepository.list_by_resource ({resource_type}/{resource_id}): {e}", exc_info=True)
            return []

    def list_by_workspace(self, workspace_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """按 workspace_id 查询审计历史。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(AuditLog)
                    .where(AuditLog.workspace_id == workspace_id)
                    .order_by(AuditLog.pr_key_id.desc())
                    .limit(limit)
                )
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"AuditRepository.list_by_workspace ({workspace_id}): {e}", exc_info=True)
            return []

    def get_by_audit_id(self, audit_id: str) -> dict[str, Any] | None:
        """按 audit_id 字段查单条审计日志（详情查询用，非主键 pr_key_id）。

        前端详情查询传 audit_id（AUDIT_xxx 字符串），不是自增主键 pr_key_id，
        故不能用 BaseRepository.get_by_id（按主键查）。
        """
        try:
            with self._get_session() as session:
                stmt = select(AuditLog).where(AuditLog.audit_id == audit_id)
                entity = session.scalar(stmt)
                return self._entity_to_dict(entity, session) if entity else None
        except Exception as e:
            logger.error(f"AuditRepository.get_by_audit_id ({audit_id}): {e}", exc_info=True)
            return None

    def list_by_filters(self, username: str | None = None, resource_type: str | None = None,
                        action: str | None = None, workspace_id: int | None = None,
                        start_date: str | None = None, end_date: str | None = None,
                        page: int = 1, page_size: int = 20) -> tuple[list[dict[str, Any]], int]:
        """组合筛选 + 日期范围 + 分页查询。返回 (logs, total)。

        支持 username + resource_type + action + workspace_id + start_date/end_date 任意组合（AND）。
        page 从 1 开始，page_size 每页条数。
        """
        try:
            with self._get_session() as session:
                stmt = select(AuditLog)
                if username:
                    stmt = stmt.where(AuditLog.username == username)
                if resource_type:
                    stmt = stmt.where(AuditLog.resource_type == resource_type)
                if action:
                    stmt = stmt.where(AuditLog.action == action)
                if workspace_id:
                    stmt = stmt.where(AuditLog.workspace_id == workspace_id)
                if start_date:
                    stmt = stmt.where(AuditLog.create_time >= start_date)
                if end_date:
                    stmt = stmt.where(AuditLog.create_time <= end_date)
                # 总数
                total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
                # 分页
                offset = (page - 1) * page_size
                stmt = stmt.order_by(AuditLog.pr_key_id.desc()).offset(offset).limit(page_size)
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities], total
        except Exception as e:
            logger.error(f"AuditRepository.list_by_filters failed: {e}", exc_info=True)
            return [], 0

    def summary(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """5 维度聚合报表（按日期范围）：资源类型/操作类型/用户/日期趋势/状态码分布。"""
        try:
            with self._get_session() as session:
                where = ""
                params = {}
                if start_date:
                    where += " AND create_time >= :start"
                    params['start'] = start_date
                if end_date:
                    where += " AND create_time <= :end"
                    params['end'] = end_date

                def _group(sql: str):
                    rows = session.execute(text(sql), params).fetchall()
                    return [{'key': str(r[0]) if r[0] is not None else '(空)', 'count': r[1]} for r in rows]

                by_rt = _group(
                    "SELECT resource_type, COUNT(*) cnt FROM tb_audit_log WHERE 1=1" + where
                    + " AND resource_type IS NOT NULL GROUP BY resource_type ORDER BY cnt DESC"
                )
                by_action = _group(
                    "SELECT action, COUNT(*) cnt FROM tb_audit_log WHERE 1=1" + where
                    + " AND action IS NOT NULL GROUP BY action ORDER BY cnt DESC"
                )
                by_user = _group(
                    "SELECT username, COUNT(*) cnt FROM tb_audit_log WHERE 1=1" + where
                    + " AND username IS NOT NULL GROUP BY username ORDER BY cnt DESC LIMIT 10"
                )
                by_date = _group(
                    "SELECT DATE(create_time) d, COUNT(*) cnt FROM tb_audit_log WHERE 1=1" + where
                    + " GROUP BY DATE(create_time) ORDER BY d DESC LIMIT 30"
                )
                by_status = _group(
                    "SELECT status_code, COUNT(*) cnt FROM tb_audit_log WHERE 1=1" + where
                    + " AND status_code IS NOT NULL GROUP BY status_code ORDER BY cnt DESC"
                )
                total = session.execute(
                    text("SELECT COUNT(*) FROM tb_audit_log WHERE 1=1" + where), params
                ).scalar() or 0
                return {
                    'by_resource_type': by_rt,
                    'by_action': by_action,
                    'by_user': by_user,
                    'by_date': by_date,
                    'by_status': by_status,
                    'total': total,
                }
        except Exception as e:
            logger.error(f"AuditRepository.summary failed: {e}", exc_info=True)
            return {}

    def list_usernames(self, q: str | None = None, limit: int = 10) -> list[str]:
        """distinct username 模糊匹配（联想补全用）。"""
        try:
            with self._get_session() as session:
                stmt = select(AuditLog.username).distinct().where(AuditLog.username.isnot(None))
                if q:
                    stmt = stmt.where(AuditLog.username.like(f"%{q}%"))
                stmt = stmt.limit(limit)
                rows = session.execute(stmt).fetchall()
                return [r[0] for r in rows if r[0]]
        except Exception as e:
            logger.error(f"AuditRepository.list_usernames failed: {e}")
            return []
