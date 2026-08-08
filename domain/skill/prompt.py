from __future__ import annotations
from typing import List, Optional
from loguru import logger
from .entities import Skill, SkillSource
from .storage.base import SkillStorage
class SkillPromptGenerator:
    CONTAINER_BASE_PATH = "/mnt/skills"
    def __init__(self, storages: List[SkillStorage]):
        self._storages = storages
        self._skills: Optional[List[Skill]] = None
    def load_skills(self, enabled_only: bool = True) -> List[Skill]:
        all_skills: List[Skill] = []
        for storage in self._storages:
            try:
                skills = storage.load_skills(enabled_only=enabled_only)
                all_skills.extend(skills)
            except Exception as e:
                logger.warning(
                    f"[SkillPromptGenerator]  "
                    f"({type(storage).__name__}): {e}"
                )
        seen: dict[str, Skill] = {}
        for skill in all_skills:
            if skill.name not in seen:
                seen[skill.name] = skill
            elif skill.source == SkillSource.DATABASE:
                seen[skill.name] = skill
        self._skills = list(seen.values())
        logger.info(
            f"[SkillPromptGenerator]  {len(self._skills)} "
        )
        return self._skills
    def generate_metadata_section(self) -> str:
        if not self._skills:
            return ""
        items = "\n".join(
            f"    {skill.format_metadata_xml(self.CONTAINER_BASE_PATH)}"
            for skill in self._skills
        )
        return f"<available_skills>\n{items}\n</available_skills>"
    def generate_full_section(self) -> str:
        skills_list = self.generate_metadata_section()
        if not skills_list:
            return ""
        return f"""<skill_system>
You have access to skills that provide optimized workflows for specific tasks. Each skill contains best practices, frameworks, and references to additional resources.
**Progressive Loading Pattern:**
1. When a user query matches a skill's use case, immediately call `read_file` tool with the skill's location path as the file_path argument
2. Read and understand the skill's workflow and instructions
3. The skill file contains references to external resources under the same folder
4. Load referenced resources only when needed during execution
5. Follow the skill's instructions precisely
**IMPORTANT:** Skills are NOT tools. Do NOT call skill names as tool names. To use a skill, call `read_file` with the skill's `<location>` path.
**Skills are located at:** {self.CONTAINER_BASE_PATH}
{skills_list}
</skill_system>"""
    @property
    def skills(self) -> List[Skill]:
        return self._skills or []
    def get_skill_by_name(self, name: str) -> Optional[Skill]:
        for skill in (self._skills or []):
            if skill.name == name:
                return skill
        return None
    def get_disk_skills(self) -> List[Skill]:
        return [
            s for s in (self._skills or [])
            if s.source == SkillSource.DISK
        ]
    def get_database_skills(self) -> List[Skill]:
        return [
            s for s in (self._skills or [])
            if s.source == SkillSource.DATABASE
        ]