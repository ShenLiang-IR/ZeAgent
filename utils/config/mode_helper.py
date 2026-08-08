import contextvars
from typing import Optional, Dict
from loguru import logger
from utils.config import get_config_db
_preview_context: contextvars.ContextVar[Optional[Dict[str, str]]] = contextvars.ContextVar(
    'preview_context', default=None
)


def get_mode_prompt_suffix(mode_name: Optional[str]) -> Optional[str]:
    """根据模式名称查询对应的提示词后缀（comprehe_sugg_content）。

    从 config_db.modes 按 en_name 或 dclr_ptn_name 查找，
    返回 comprehe_sugg_content 字段值；未找到时返回 None。
    """
    if not mode_name:
        return None
    try:
        config_db = get_config_db()
        mode = config_db.modes.get_by_name(mode_name)
        if not mode:
            # 尝试用 dclr_ptn_name 查
            modes = config_db.modes.get_all()
            for m in modes:
                if m.get('dclr_ptn_name') == mode_name or m.get('en_name') == mode_name:
                    mode = m
                    break
        if mode:
            suffix = mode.get('comprehe_sugg_content') or mode.get('system_prompt_suffix')
            if suffix:
                logger.debug(f"[mode_helper] mode={mode_name}, suffix_len={len(suffix)}")
                return suffix
        return None
    except Exception as e:
        logger.warning(f"[mode_helper] get_mode_prompt_suffix failed: {e}")
        return None


def set_preview_context(
    system_prompt_suffix: Optional[str] = None,
    planning_guidance: Optional[str] = None,
    execution_guidance: Optional[str] = None,
    recommended_agents: Optional[str] = None,
    priority_agent: Optional[str] = None
) -> None:
    if (system_prompt_suffix is None and planning_guidance is None
        and execution_guidance is None and recommended_agents is None
        and priority_agent is None):
        _preview_context.set(None)
    else:
        _preview_context.set({
            'system_prompt_suffix': system_prompt_suffix or '',
            'planning_guidance': planning_guidance or '',
            'execution_guidance': execution_guidance or '',
            'recommended_agents': recommended_agents or '',
            'priority_agent': priority_agent or ''
        })
def get_preview_context() -> Optional[Dict[str, str]]:
    return _preview_context.get()
def clear_preview_context() -> None:
    _preview_context.set(None)
