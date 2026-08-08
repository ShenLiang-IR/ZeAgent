from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from ..entities import Skill
class SkillStorage(ABC):
    @abstractmethod
    def _discover_skills(self) -> List[Skill]:
        ...
    def load_skills(self, enabled_only: bool = False) -> List[Skill]:
        skills = self._discover_skills()
        if enabled_only:
            skills = [s for s in skills if s.enabled]
        skills.sort(key=lambda s: s.name)
        return skills
    @abstractmethod
    def read_skill_content(self, skill: Skill) -> str:
        ...
    @abstractmethod
    def read_resource(self, skill: Skill, relative_path: str) -> Optional[str]:
        ...