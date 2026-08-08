from __future__ import annotations
import os
from pathlib import Path
from typing import List, Optional
from loguru import logger
from ..entities import Skill
from ..parser import parse_skill_md
from .base import SkillStorage
SKILL_MD_FILE = "SKILL.md"
class LocalSkillStorage(SkillStorage):
    def __init__(self, skills_dir: str | Path):
        self._root = Path(skills_dir)
    def _discover_skills(self) -> List[Skill]:
        if not self._root.is_dir():
            logger.warning(f"[LocalSkillStorage] : {self._root}")
            return []
        skills: List[Skill] = []
        for root, dirs, files in os.walk(self._root):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            if SKILL_MD_FILE in files:
                skill_file = Path(root) / SKILL_MD_FILE
                skill = parse_skill_md(skill_file)
                if skill:
                    skills.append(skill)
                    logger.debug(
                        f"[LocalSkillStorage] : {skill.name} "
                        f"({skill.skill_dir})"
                    )
        logger.info(f"[LocalSkillStorage]  {len(skills)} ")
        return skills
    def read_skill_content(self, skill: Skill) -> str:
        if skill.cached_content:
            return skill.cached_content
        if skill.skill_file:
            try:
                return Path(skill.skill_file).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(f"[LocalSkillStorage] : {skill.skill_file} — {e}")
                return ""
        return ""
    def read_resource(self, skill: Skill, relative_path: str) -> Optional[str]:
        if not skill.skill_dir:
            return None
        resource_path = Path(skill.skill_dir) / relative_path
        try:
            resource_path = resource_path.resolve()
            skill_dir_resolved = Path(skill.skill_dir).resolve()
            if not str(resource_path).startswith(str(skill_dir_resolved)):
                logger.warning(
                    f"[LocalSkillStorage] : {relative_path}"
                )
                return None
        except (ValueError, OSError):
            return None
        allowed_dirs = {"references", "templates", "scripts", "assets"}
        try:
            rel = resource_path.relative_to(skill_dir_resolved)
            if rel.parts and rel.parts[0] not in allowed_dirs:
                logger.warning(
                    f"[LocalSkillStorage] : {relative_path}"
                )
                return None
        except ValueError:
            return None
        try:
            return resource_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None