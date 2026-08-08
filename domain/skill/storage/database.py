from __future__ import annotations
from typing import List, Optional
from loguru import logger
from ..entities import Skill, SkillMetadata, SkillSource
from .base import SkillStorage
class DatabaseSkillStorage(SkillStorage):
    def __init__(self, repository=None):
        self._repository = repository
        self._skills_cache: Optional[List[Skill]] = None
    def _ensure_repository(self):
        if self._repository is None:
            from infrastructure.database.repositories.skill_repository import SkillRepository
            self._repository = SkillRepository()
    def _discover_skills(self) -> List[Skill]:
        self._ensure_repository()
        try:
            skills_data = self._repository.get_all(enabled_only=True)
        except Exception as e:
            logger.error(f"[DatabaseSkillStorage] : {e}")
            return []
        if not skills_data:
            logger.info("[DatabaseSkillStorage] ")
            return []
        skills: List[Skill] = []
        for skill_data in skills_data:
            try:
                metadata = SkillMetadata.from_database(skill_data)
                skill = self._metadata_to_skill(metadata, skill_data)
                skills.append(skill)
            except Exception as e:
                skill_id = skill_data.get("skill_id", "unknown")
                logger.warning(
                    f"[DatabaseSkillStorage]  {skill_id} : {e}"
                )
        logger.info(
            f"[DatabaseSkillStorage]  {len(skills)} "
        )
        self._skills_cache = skills
        return skills
    @staticmethod
    def _metadata_to_skill(metadata: SkillMetadata, raw_data: dict) -> Skill:
        return Skill(
            name=_sanitize_name(metadata.skill_id),
            description=metadata.skill_desc[:1024] if metadata.skill_desc else metadata.skill_name,
            category=metadata.category,
            source=SkillSource.DATABASE,
            db_pr_key_id=raw_data.get("pr_key_id"),
            cached_content=metadata.build_full_content(),
            allowed_tools=None,
            enabled=metadata.enabled,
            metadata=metadata,
        )
    def read_skill_content(self, skill: Skill) -> str:
        if skill.cached_content:
            return skill.cached_content
        if skill.metadata:
            return skill.metadata.build_full_content()
        return skill.description
    def read_resource(self, skill: Skill, relative_path: str) -> Optional[str]:
        return None
    def get_skills_by_agent(self, agent_pr_key_id: str) -> List[Skill]:
        if self._skills_cache is None:
            self._discover_skills()
        try:
            from infrastructure.database.repositories.agent_relation_repository import AgentRelationRepository
            from infrastructure.database.repositories.skill_repository import SkillRepository
            agent_relation_repo = AgentRelationRepository()
            skill_repo = SkillRepository()
            pr_key_ids = agent_relation_repo.get_skill_ids(agent_pr_key_id)
            if not pr_key_ids:
                return []
            bound_skills: List[Skill] = []
            for pr_key_id in pr_key_ids:
                skill_data = skill_repo.get_by_id(pr_key_id, return_dict=True)
                if not skill_data:
                    continue
                skill_id = skill_data.get("skill_id", "")
                if self._skills_cache:
                    match = next(
                        (s for s in self._skills_cache if s.name == _sanitize_name(skill_id)),
                        None,
                    )
                    if match:
                        bound_skills.append(match)
                        continue
                try:
                    metadata = SkillMetadata.from_database(skill_data)
                    bound_skills.append(self._metadata_to_skill(metadata, skill_data))
                except Exception as e:
                    logger.warning(
                        f"[DatabaseSkillStorage]  {skill_id} : {e}"
                    )
            return bound_skills
        except Exception as e:
            logger.error(
                f"[DatabaseSkillStorage]  Agent {agent_pr_key_id} : {e}"
            )
            return []
def _sanitize_name(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9-]", "-", name.lower())[:64]