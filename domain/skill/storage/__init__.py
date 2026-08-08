from .base import SkillStorage
from .local import LocalSkillStorage
from .database import DatabaseSkillStorage

__all__ = ["SkillStorage", "LocalSkillStorage", "DatabaseSkillStorage", "create_skill_storages"]


def create_skill_storages(caller_file: str, db_repository=None) -> list:
    """创建技能存储层的共享工厂函数。

    消除 SkillRegistry._init_prompt_generator() 与
    subagent_builder._ensure_skill_file_reader_initialized() 中的重复初始化逻辑。

    Args:
        caller_file: 调用方的 __file__（用于解析 skills_dir 的相对路径）。
        db_repository: 可选的 DB repository（SkillRegistry 需要传入）。
    Returns:
        List[SkillStorage]: DatabaseSkillStorage + LocalSkillStorage（如果已配置）。
    """
    from utils.config import get_config
    from pathlib import Path
    storages = []
    try:
        db_storage = DatabaseSkillStorage(repository=db_repository)
        storages.append(db_storage)
    except Exception:
        pass
    skills_dir_cfg = get_config('agent.skills_dir')
    if skills_dir_cfg:
        skills_dir = Path(skills_dir_cfg)
        if not skills_dir.is_absolute():
            app_dir = Path(caller_file).resolve().parent.parent.parent
            skills_dir = app_dir / skills_dir_cfg
        if skills_dir.is_dir():
            storages.append(LocalSkillStorage(skills_dir))
    return storages