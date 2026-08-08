from __future__ import annotations
from pathlib import PurePosixPath
from typing import Optional
from loguru import logger
from .entities import Skill
from .storage.local import LocalSkillStorage
from .storage.database import DatabaseSkillStorage
SKILLS_BASE_PATH = "/mnt/skills"
PUBLIC_PREFIX = "/mnt/skills/public/"
CUSTOM_PREFIX = "/mnt/skills/custom/"
class SkillFileReader:
    def __init__(
        self,
        disk_storage: Optional[LocalSkillStorage] = None,
        db_storage: Optional[DatabaseSkillStorage] = None,
    ):
        self._disk_storage = disk_storage
        self._db_storage = db_storage
        self._disk_skills: dict[str, Skill] = {}
        self._db_skills: dict[str, Skill] = {}
    def load_skills(self) -> None:
        if self._disk_storage:
            for skill in self._disk_storage.load_skills(enabled_only=True):
                self._disk_skills[skill.name] = skill
        if self._db_storage:
            for skill in self._db_storage.load_skills(enabled_only=True):
                self._db_skills[skill.name] = skill
        logger.info(
            f"[SkillFileReader] : "
            f"={len(self._disk_skills)}, ={len(self._db_skills)}"
        )
    @staticmethod
    def is_skills_path(path: str) -> bool:
        return path.strip().startswith(SKILLS_BASE_PATH + "/")
    def read_file(self, virtual_path: str) -> str:
        path = virtual_path.strip()
        if not self.is_skills_path(path):
            raise FileNotFoundError(
                f": {virtual_path}"
                f" {SKILLS_BASE_PATH}/ "
            )
        if path.startswith(CUSTOM_PREFIX):
            return self._read_custom_skill(path)
        if path.startswith(PUBLIC_PREFIX):
            return self._read_public_skill(path)
        raise FileNotFoundError(
            f"无效的技能路径: {virtual_path}，需以 {PUBLIC_PREFIX} 或 {CUSTOM_PREFIX} 开头"
        )
    def list_available_paths(self) -> list[str]:
        paths = []
        for name in sorted(self._disk_skills):
            paths.append(f"{PUBLIC_PREFIX}{name}/SKILL.md")
        for name in sorted(self._db_skills):
            paths.append(f"{CUSTOM_PREFIX}{name}/SKILL.md")
        return paths
    def _read_public_skill(self, path: str) -> str:
        if not self._disk_storage:
            raise FileNotFoundError("")
        relative = path[len(PUBLIC_PREFIX):]
        parts = PurePosixPath(relative).parts
        if not parts:
            raise FileNotFoundError(f"无效的技能路径: {path}")
        skill_name = parts[0]
        skill = self._disk_skills.get(skill_name)
        if not skill:
            raise FileNotFoundError(
                f"技能不存在: {skill_name}，可用技能: {', '.join(sorted(self._disk_skills))}"
            )
        if len(parts) == 2 and parts[1] == "SKILL.md":
            return self._disk_storage.read_skill_content(skill)
        if len(parts) >= 3:
            resource_relative = str(PurePosixPath(*parts[1:]))
            content = self._disk_storage.read_resource(skill, resource_relative)
            if content is None:
                raise FileNotFoundError(
                    f"技能资源不存在: {resource_relative} "
                    f"(技能: {skill_name})"
                )
            return content
        raise FileNotFoundError(f"无效的技能路径: {path}")
    def _read_custom_skill(self, path: str) -> str:
        if not self._db_storage:
            raise FileNotFoundError("数据库技能存储未配置")
        relative = path[len(CUSTOM_PREFIX):]
        parts = PurePosixPath(relative).parts
        if not parts:
            raise FileNotFoundError(f"无效的技能路径: {path}")
        skill_name = parts[0]
        skill = self._db_skills.get(skill_name)
        if not skill:
            raise FileNotFoundError(
                f": {skill_name}"
                f": {', '.join(sorted(self._db_skills))}"
            )
        return self._db_storage.read_skill_content(skill)