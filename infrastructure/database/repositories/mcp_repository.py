import json
from loguru import logger
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from infrastructure.database.sessions import get_config_session
from infrastructure.database.models.mcp import Mcp, McpIntfc
from infrastructure.database.repositories.base_repository import BaseRepository
class McpRepository(BaseRepository[Mcp, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Mcp
    def _entity_to_dict(self, entity: Mcp, session: Session) -> Dict[str, Any]:
        params_dict = {}
        if entity.params:
            try:
                params_dict = json.loads(entity.params) if isinstance(entity.params, str) else entity.params
            except (json.JSONDecodeError, TypeError):
                params_dict = {}
        return {
            'pr_key_id': entity.pr_key_id,
            'mcp_id': entity.mcp_id or '',
            'mcp_name': entity.mcp_name or '',
            'description': entity.description or '',
            'category': entity.category or '',
            'exec_cmd': entity.exec_cmd or '',
            'connection_type': entity.connection_type or '',
            'connection_url': entity.connection_url or '',
            'auth_info': entity.auth_info or '',
            'timeout': entity.timeout or 30000,
            'params': params_dict,
            'status': entity.status or '1',
            'enabled': entity.status == '1',
            'workspace_id': entity.workspace_id,
            'is_public': entity.is_public if entity.is_public is not None else 0,
            'visibility': entity.visibility or '',
            'creator_id': entity.creator_id,
        }
    _pk_name = 'pr_key_id'
    def get_all(self, enabled_only: bool = False, workspace_id: int = None,
                viewer_user_id: int = None, viewer_workspace_id: int = None,
                is_admin: bool = False) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Mcp).where(Mcp.del_flag == '0')
            if enabled_only:
                stmt = stmt.where(Mcp.status == '1')
            # 三层可见性过滤（优先）；未提供 viewer_user_id 时回退旧 workspace 精确匹配
            if viewer_user_id is not None or is_admin:
                from utils.common.visibility import build_visibility_orm_filter
                vis_filter = build_visibility_orm_filter(
                    Mcp, viewer_user_id, viewer_workspace_id, is_admin,
                )
                if vis_filter is not None:
                    stmt = stmt.where(vis_filter)
            elif workspace_id is not None:
                stmt = stmt.where(Mcp.workspace_id == workspace_id)
            stmt = stmt.order_by(Mcp.mcp_id)
            entities = session.scalars(stmt).all()
            result = [self._entity_to_dict(e, session) for e in entities]
            logger.debug(f"[Repository] get_all: enabled_only={enabled_only},  {len(result)}  MCP")
            return result
    def get_by_id(self, pr_key_id: str, return_dict: bool = True) -> Optional[Mcp | Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Mcp).where(
                and_(
                    Mcp.pr_key_id == pr_key_id,
                    Mcp.del_flag == '0'
                )
            )
            entity = session.scalar(stmt)
            if entity:
                if return_dict:
                    return self._entity_to_dict(entity, session)
                return entity
            return None
    def get_by_name(self, mcp_name: str) -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(Mcp).where(
                and_(
                    Mcp.mcp_name == mcp_name,
                    Mcp.del_flag == '0'
                )
            )
            result = session.execute(stmt)
            entity = result.scalar_one_or_none()
            if entity:
                return self._entity_to_dict(entity, session)
            return None

    def get_by_mcp_id(self, mcp_id: str) -> Optional[Dict[str, Any]]:
        """按业务 mcp_id 查询（插件市场卸载时用于定位关联 MCP 的 pr_key_id）。"""
        with self._get_session() as session:
            stmt = select(Mcp).where(
                and_(
                    Mcp.mcp_id == mcp_id,
                    Mcp.del_flag == '0'
                )
            )
            entity = session.scalar(stmt)
            if entity:
                return self._entity_to_dict(entity, session)
            return None
    def save_mcp(
        self,
        pr_key_id: str,
        mcp_name: str,
        mcp_id: str = "",
        connection_type: str = "",
        connection_url: str = "",
        description: str = "",
        category: str = "",
        exec_cmd: str = "",
        auth_info: str = "",
        timeout: int = 30000,
        params: Dict[str, Any] = None,
        enabled: bool = True,
        workspace_id: int = None,
        visibility: str = None,
        creator_id: int = None,
    ) -> bool:
        from utils.common.visibility import normalize_visibility, visibility_to_is_public
        try:
            existing = self.get_by_id(pr_key_id, return_dict=True)
            mcp_data = {
                'mcp_name': mcp_name,
                'mcp_id': mcp_id or None,
                'description': description,
                'category': category,
                'exec_cmd': exec_cmd,
                'connection_type': connection_type,
                'connection_url': connection_url,
                'auth_info': auth_info,
                'timeout': timeout,
                'params': json.dumps(params) if params else None,
                'status': '1' if enabled else '0',
                'del_flag': '0'
            }
            if workspace_id is not None:
                mcp_data['workspace_id'] = workspace_id
            # 三层可见性：visibility 为 source of truth，同步 is_public
            if visibility is not None:
                visibility = normalize_visibility(visibility)
                mcp_data['visibility'] = visibility
                mcp_data['is_public'] = visibility_to_is_public(visibility)
            if creator_id is not None:
                mcp_data['creator_id'] = creator_id
            with self._get_session() as session:
                if existing:
                    stmt = select(Mcp).where(Mcp.pr_key_id == pr_key_id)
                    entity = session.scalar(stmt)
                    if entity:
                        for key, value in mcp_data.items():
                            if hasattr(entity, key):
                                setattr(entity, key, value)
                else:
                    entity = Mcp(**mcp_data)
                    session.add(entity)
                session.commit()
            return True
        except Exception as e:
            logger.error(f"MCP: {str(e)}", exc_info=True)
            return False
    def delete_mcp(self, pr_key_id: str) -> bool:
        try:
            with self._get_session() as session:
                session.query(Mcp).filter(
                    Mcp.pr_key_id == pr_key_id
                ).update({'del_flag': '1'})
                session.commit()
            return True
        except Exception as e:
            logger.error(f"MCP: {str(e)}", exc_info=True)
            return False
    def save_mcp_config(
        self,
        name: str,
        display_name: str = "",
        description: str = "",
        version: str = "1.0.0",
        config_json: Dict[str, Any] = None,
        enabled: bool = True,
        tool_sets: List[Dict[str, Any]] = None
    ) -> bool:
        try:
            config = config_json or {}
            connection_type = config.get('mcp_type', config.get('connection_type', ''))
            connection_url = config.get('url', config.get('connection_url', ''))
            exec_cmd = config.get('command', config.get('exec_cmd', ''))
            auth_info = config.get('auth_info', '')
            timeout = config.get('timeout', 30000)
            params = config.get('params', {})
            mcp_id = f"MCP_{name}" if not name.startswith("MCP_") else name
            return self.save_mcp(
                mcp_id=mcp_id,
                mcp_name=name,
                connection_type=connection_type,
                connection_url=connection_url,
                description=description or display_name,
                exec_cmd=exec_cmd,
                auth_info=auth_info,
                timeout=timeout,
                params=params,
                enabled=enabled
            )
        except Exception as e:
            logger.error(f"MCP(save_mcp_config): {str(e)}", exc_info=True)
            return False
    def update(self, pr_key_id: str, **kwargs) -> Optional[Mcp]:
        try:
            return super().update(pr_key_id, **kwargs)
        except Exception as e:
            logger.error(f"MCP: {str(e)}", exc_info=True)
            return None
    def delete(self, pr_key_id: str) -> bool:
        return self.delete_mcp(pr_key_id)
    def update_conn_status(self, pr_key_id: str, conn_status: str) -> bool:
        return True
class McpIntfcRepository(BaseRepository[McpIntfc, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = McpIntfc
    def _entity_to_dict(self, entity: McpIntfc, session: Session) -> Dict[str, Any]:
        input_param_ex_dict = {}
        if entity.input_param_ex:
            try:
                input_param_ex_dict = json.loads(entity.input_param_ex) if isinstance(entity.input_param_ex, str) else entity.input_param_ex
            except (json.JSONDecodeError, TypeError):
                input_param_ex_dict = {}
        output_param_ex_dict = {}
        if entity.output_param_ex:
            try:
                output_param_ex_dict = json.loads(entity.output_param_ex) if isinstance(entity.output_param_ex, str) else entity.output_param_ex
            except (json.JSONDecodeError, TypeError):
                output_param_ex_dict = {}
        return {
            'pr_key_id': entity.pr_key_id,
            'intfc_name': entity.intfc_name or '',
            'description': entity.description or '',
            'mcp_id': entity.mcp_id or '',
            'input_param_ex': input_param_ex_dict,
            'output_param_ex': output_param_ex_dict,
            'status': entity.status or '1',
            'intfc_usage': entity.intfc_usage or '',
            'enabled': entity.status == '1',
        }
    _pk_name = 'pr_key_id'
    def get_by_mcp_id(self, mcp_id: str) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(McpIntfc).where(
                and_(
                    McpIntfc.mcp_id == mcp_id,
                    McpIntfc.del_flag == '0'
                )
            )
            entities = session.scalars(stmt).all()
            result = [self._entity_to_dict(e, session) for e in entities]
            logger.debug(f"[McpIntfcRepository] get_by_mcp_id: mcp_id={mcp_id},  {len(result)} ")
            return result
    def save_interface(
        self,
        pr_key_id: str,
        intfc_name: str,
        mcp_id: str,
        description: str = "",
        input_param_ex: Dict[str, Any] = None,
        output_param_ex: Dict[str, Any] = None,
        intfc_usage: str = "1",
        enabled: bool = True
    ) -> bool:
        try:
            intfc_data = {
                'intfc_name': intfc_name,
                'description': description,
                'mcp_id': mcp_id,
                'input_param_ex': json.dumps(input_param_ex) if input_param_ex else None,
                'output_param_ex': json.dumps(output_param_ex) if output_param_ex else None,
                'intfc_usage': intfc_usage,
                'status': '1' if enabled else '0',
                'del_flag': '0'
            }
            entity = self.upsert(pr_key_id, **intfc_data)
            return entity is not None
        except Exception as e:
            logger.error(f"MCP: {str(e)}", exc_info=True)
            return False