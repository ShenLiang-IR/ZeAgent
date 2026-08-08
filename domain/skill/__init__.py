from .entities import (
    SkillCategory,
    SkillSource,
    SkillParameter,
    SkillMetadata,
    SkillExecutionResult,
    SkillTriggerHint,
    SkillResource,
    Skill,
)
__all__ = [
    "SkillCategory",
    "SkillSource",
    "SkillParameter",
    "SkillMetadata",
    "SkillExecutionResult",
    "SkillTriggerHint",
    "SkillResource",
    "Skill",
    "LazySkillProxy",
    "SkillLoader",
    "SkillRegistry",
    "get_skill_registry",
]
def __getattr__(name):
    if name == "LazySkillProxy":
        from .lazy_skill import LazySkillProxy
        return LazySkillProxy
    if name == "SkillLoader":
        from .loader import SkillLoader
        return SkillLoader
    if name == "SkillRegistry":
        from .registry import SkillRegistry
        return SkillRegistry
    if name == "get_skill_registry":
        from .registry import get_skill_registry
        return get_skill_registry
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")