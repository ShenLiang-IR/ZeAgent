from __future__ import annotations

def should_use_skill_backend() -> bool:
    """检查是否启用 skill backend（从配置读取）。"""
    from utils.config import get_config
    use_skill_backend = get_config('agent.use_skill_backend', True)
    return use_skill_backend