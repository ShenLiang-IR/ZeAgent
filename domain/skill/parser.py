from __future__ import annotations
import re
from pathlib import Path
from typing import Optional, Tuple
from loguru import logger
from .entities import Skill, SkillCategory, SkillSource
def parse_skill_md(file_path: Path) -> Optional[Skill]:
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"[parser]  SKILL.md : {file_path} — {e}")
        return None
    frontmatter, body = _split_frontmatter(content)
    if frontmatter is None:
        logger.warning(f"[parser] SKILL.md  YAML frontmatter: {file_path}")
        return None
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if not name:
        name = file_path.parent.name
    if not description:
        description = body.strip().split("\n")[0] if body.strip() else ""
    allowed_tools = frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools")
    if isinstance(allowed_tools, str):
        allowed_tools = [t.strip() for t in allowed_tools.split(",") if t.strip()]
    category_str = frontmatter.get("category", "general")
    category = SkillCategory.from_string(category_str)
    enabled = frontmatter.get("enabled", True)
    return Skill(
        name=_sanitize_name(str(name)),
        description=str(description)[:1024],
        category=category,
        source=SkillSource.DISK,
        skill_dir=str(file_path.parent),
        skill_file=str(file_path),
        cached_content=body,
        allowed_tools=allowed_tools,
        enabled=bool(enabled),
    )
def _split_frontmatter(content: str) -> Tuple[Optional[dict], str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return None, content
    yaml_str = match.group(1)
    body = match.group(2)
    try:
        import yaml
        frontmatter = yaml.safe_load(yaml_str)
        if not isinstance(frontmatter, dict):
            return None, content
        return frontmatter, body
    except ImportError:
        return _parse_simple_yaml(yaml_str), body
    except Exception as e:
        logger.warning(f"[parser] YAML : {e}")
        return None, content
def _parse_simple_yaml(yaml_str: str) -> dict:
    result = {}
    for line in yaml_str.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        result[key] = value
    return result
def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", name.lower())[:64]