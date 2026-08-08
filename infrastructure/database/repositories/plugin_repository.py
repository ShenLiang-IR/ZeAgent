"""插件市场仓储层。"""
import json
from typing import Any, Dict, List, Optional
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from ..base import Base
from ..models.plugin import Plugin, PluginInstall
from ..sessions import get_config_session, get_config_engine
from .base_repository import BaseRepository


def _parse_json(value: Optional[str]) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value) if isinstance(value, str) else (value or {})
    except (json.JSONDecodeError, TypeError):
        return {}


class PluginRepository(BaseRepository[Plugin, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = Plugin
    _pk_name = 'id'

    def __init__(self):
        super().__init__()
        Base.metadata.create_all(get_config_engine(), tables=[Plugin.__table__], checkfirst=True)

    def _entity_to_dict(self, entity: Plugin, session: Session) -> Dict[str, Any]:
        return {
            'id': entity.id,
            'plugin_id': entity.plugin_id or '',
            'name': entity.name or '',
            'display_name': entity.display_name or '',
            'description': entity.description or '',
            'icon': entity.icon or '',
            'category': entity.category or '',
            'tags': (entity.tags or '').split(',') if entity.tags else [],
            'author': entity.author or '',
            'version': entity.version or '1.0.0',
            'plugin_type': entity.plugin_type or 'mcp_server',
            'mcp_config': _parse_json(entity.mcp_config),
            'manifest': _parse_json(entity.manifest),
            'status': entity.status or '1',
            'download_count': entity.download_count or 0,
            'rating': entity.rating,
            'workspace_id': entity.workspace_id,
        }

    def get_by_plugin_id(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            entity = session.scalar(
                select(Plugin).where(Plugin.plugin_id == plugin_id, Plugin.del_flag == '0')
            )
            return self._entity_to_dict(entity, session) if entity else None

    def get_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            entity = session.scalar(
                select(Plugin).where(Plugin.name == name, Plugin.del_flag == '0')
            )
            return self._entity_to_dict(entity, session) if entity else None

    def list_marketplace(
        self,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        status: str = '1',
        workspace_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """浏览市场：按分类/关键词过滤，仅上架（status=1）插件。

        workspace_id 不为空时返回该空间发布的 + 官方全局（workspace_id IS NULL）插件。
        """
        with self._get_session() as session:
            stmt = select(Plugin).where(Plugin.del_flag == '0', Plugin.status == status)
            if category:
                stmt = stmt.where(Plugin.category == category)
            if workspace_id is not None:
                stmt = stmt.where(or_(Plugin.workspace_id == workspace_id, Plugin.workspace_id.is_(None)))
            if keyword:
                like = f"%{keyword}%"
                stmt = stmt.where(or_(
                    Plugin.display_name.like(like),
                    Plugin.name.like(like),
                    Plugin.description.like(like),
                    Plugin.tags.like(like),
                ))
            stmt = stmt.order_by(Plugin.download_count.desc(), Plugin.id.desc()).offset(offset).limit(limit)
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]

    def list_categories(self) -> List[str]:
        """返回所有已上架插件的分类（去重）。"""
        with self._get_session() as session:
            stmt = select(Plugin.category).where(Plugin.del_flag == '0', Plugin.status == '1').distinct()
            return [c for c in session.scalars(stmt).all() if c]

    def save_plugin(self, **kwargs) -> Optional[Plugin]:
        mcp_config = kwargs.pop('mcp_config', None)
        manifest = kwargs.pop('manifest', None)
        if isinstance(mcp_config, dict):
            kwargs['mcp_config'] = json.dumps(mcp_config, ensure_ascii=False)
        if isinstance(manifest, dict):
            kwargs['manifest'] = json.dumps(manifest, ensure_ascii=False)
        tags = kwargs.get('tags')
        if isinstance(tags, list):
            kwargs['tags'] = ','.join(tags)
        return self.create(**kwargs)

    def increment_download(self, plugin_id: str) -> bool:
        with self._get_session() as session:
            entity = session.scalar(select(Plugin).where(Plugin.plugin_id == plugin_id))
            if not entity:
                return False
            entity.download_count = (entity.download_count or 0) + 1
            session.commit()
            return True

    def soft_delete(self, plugin_id: str) -> bool:
        with self._get_session() as session:
            entity = session.scalar(select(Plugin).where(Plugin.plugin_id == plugin_id))
            if not entity:
                return False
            entity.del_flag = '1'
            session.commit()
            return True


class PluginInstallRepository(BaseRepository[PluginInstall, Dict[str, Any]]):
    _session_factory = get_config_session
    _model_class = PluginInstall
    _pk_name = 'id'

    def __init__(self):
        super().__init__()
        Base.metadata.create_all(get_config_engine(), tables=[PluginInstall.__table__], checkfirst=True)

    def _entity_to_dict(self, entity: PluginInstall, session: Session) -> Dict[str, Any]:
        return {
            'id': entity.id,
            'install_id': entity.install_id or '',
            'plugin_id': entity.plugin_id or '',
            'version': entity.version or '',
            'workspace_id': entity.workspace_id,
            'user_id': entity.user_id,
            'config': _parse_json(entity.config),
            'linked_mcp_id': entity.linked_mcp_id or '',
            'linked_resource_id': entity.linked_resource_id or entity.linked_mcp_id or '',
            'enabled': entity.enabled or '1',
        }

    def get_by_install_id(self, install_id: str) -> Optional[Dict[str, Any]]:
        """按业务 install_id 查询安装记录。"""
        with self._get_session() as session:
            entity = session.scalar(
                select(PluginInstall).where(
                    PluginInstall.install_id == install_id, PluginInstall.del_flag == '0'
                )
            )
            return self._entity_to_dict(entity, session) if entity else None

    def find_install(
        self, plugin_id: str, workspace_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(PluginInstall).where(
                PluginInstall.plugin_id == plugin_id, PluginInstall.del_flag == '0'
            )
            if workspace_id is not None:
                stmt = stmt.where(PluginInstall.workspace_id == workspace_id)
            if user_id is not None:
                stmt = stmt.where(PluginInstall.user_id == user_id)
            entity = session.scalar(stmt)
            return self._entity_to_dict(entity, session) if entity else None

    def list_installed(
        self, workspace_id: Optional[int] = None, user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        with self._get_session() as session:
            stmt = select(PluginInstall).where(PluginInstall.del_flag == '0')
            if workspace_id is not None:
                stmt = stmt.where(PluginInstall.workspace_id == workspace_id)
            if user_id is not None:
                stmt = stmt.where(PluginInstall.user_id == user_id)
            stmt = stmt.order_by(PluginInstall.id.desc())
            entities = session.scalars(stmt).all()
            return [self._entity_to_dict(e, session) for e in entities]

    def save_install(self, **kwargs) -> Optional[PluginInstall]:
        config = kwargs.pop('config', None)
        if isinstance(config, dict):
            kwargs['config'] = json.dumps(config, ensure_ascii=False)
        return self.create(**kwargs)

    def set_enabled(self, install_id: str, enabled: bool) -> bool:
        with self._get_session() as session:
            entity = session.scalar(select(PluginInstall).where(PluginInstall.install_id == install_id))
            if not entity:
                return False
            entity.enabled = '1' if enabled else '0'
            session.commit()
            return True

    def soft_delete(self, install_id: str) -> bool:
        with self._get_session() as session:
            entity = session.scalar(select(PluginInstall).where(PluginInstall.install_id == install_id))
            if not entity:
                return False
            entity.del_flag = '1'
            session.commit()
            return True
