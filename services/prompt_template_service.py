"""Prompt 模板服务：{{var}} 变量插值 + CRUD。

设计参见 当前文档分析.md §3.8：Prompt 治理（MVP）。

核心 API：
- render(content, variables) -> str：{{var}} 插值（纯函数，未提供变量保留占位）
- render_template(name, variables) -> str：按名称查模板 + render
- create/get/list/update：CRUD（调 repository）

MVP 不含 A/B 测试/评测/沙箱（后续）。
"""
import re

from loguru import logger

# {{var}} 占位正则：匹配 {{ 任意单词字符 }}
_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def render(content: str, variables: dict | None = None) -> str:
    """{{var}} 变量插值。

    Args:
        content: 模板内容，含 {{var}} 占位
        variables: 变量 dict {var_name: value}

    Returns:
        插值后的字符串；未提供的变量保留原 {{var}} 占位
    """
    if not content:
        return content or ""
    if not variables:
        return content

    def _repl(m):
        var = m.group(1).strip()
        if var in variables:
            return str(variables[var])
        return m.group(0)  # 未提供，保留原占位

    return _VAR_PATTERN.sub(_repl, content)


class PromptTemplateService:
    """Prompt 模板服务。"""

    _table_ensured = False

    def _ensure_table(self):
        """确保 tb_prompt_template 表存在（幂等 lazy init）。"""
        if PromptTemplateService._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            from infrastructure.database.models.prompt_template import PromptTemplate

            Base.metadata.create_all(
                get_config_engine(),
                tables=[PromptTemplate.__table__],
                checkfirst=True,
            )
            PromptTemplateService._table_ensured = True
        except Exception as e:
            logger.warning(f"[PromptTemplate] _ensure_table failed (non-fatal): {e}")

    def render_template(self, name: str, variables: dict | None = None) -> str | None:
        """按名称查模板 + render 插值。

        Returns:
            插值后的字符串；模板不存在返回 None
        """
        self._ensure_table()
        try:
            from infrastructure.database.repositories.prompt_template_repository import PromptTemplateRepository

            template = PromptTemplateRepository().get_by_name(name)
            if not template:
                return None
            return render(template.get("content", ""), variables)
        except Exception as e:
            logger.error(f"[PromptTemplate] render_template ({name}): {e}", exc_info=True)
            return None

    def create(self, name: str, content: str, variables: list | None = None,
               version: str = "1.0.0", description: str = "",
               workspace_id: int | None = None) -> dict | None:
        """创建模板。"""
        self._ensure_table()
        try:
            import json

            from infrastructure.database.repositories.prompt_template_repository import PromptTemplateRepository
            from utils.id_generator import generate_uuid

            repo = PromptTemplateRepository()
            entity = repo.create(
                template_id=f"PT_{generate_uuid()[:16]}",
                name=name,
                content=content,
                variables=json.dumps(variables or [], ensure_ascii=False),
                version=version,
                description=description,
                workspace_id=workspace_id,
                enabled="1",
            )
            return repo._entity_to_dict(entity, None) if entity else None
        except Exception as e:
            logger.error(f"[PromptTemplate] create failed: {e}", exc_info=True)
            return None

    def get_by_name(self, name: str) -> dict | None:
        """按名称查询。"""
        self._ensure_table()
        try:
            from infrastructure.database.repositories.prompt_template_repository import PromptTemplateRepository
            return PromptTemplateRepository().get_by_name(name)
        except Exception as e:
            logger.error(f"[PromptTemplate] get_by_name ({name}): {e}", exc_info=True)
            return None

    def list_enabled(self, workspace_id: int | None = None) -> list[dict]:
        """列出启用模板。"""
        self._ensure_table()
        try:
            from infrastructure.database.repositories.prompt_template_repository import PromptTemplateRepository
            return PromptTemplateRepository().list_enabled(workspace_id)
        except Exception as e:
            logger.error(f"[PromptTemplate] list_enabled: {e}", exc_info=True)
            return []

    def update(self, pr_key_id: int, **kwargs) -> dict | None:
        """更新模板。"""
        self._ensure_table()
        try:
            from infrastructure.database.repositories.prompt_template_repository import PromptTemplateRepository
            repo = PromptTemplateRepository()
            entity = repo.update(pr_key_id, **kwargs)
            return repo._entity_to_dict(entity, None) if entity else None
        except Exception as e:
            logger.error(f"[PromptTemplate] update ({pr_key_id}): {e}", exc_info=True)
            return None
