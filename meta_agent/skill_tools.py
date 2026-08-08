"""Meta-Agent Skill 管理工具。

直接调用 SkillRepository（不经过 HTTP），返回 LLM 可读的字符串。
"""
import json
from loguru import logger
from langchain_core.tools import tool


@tool
async def create_skill(
    skill_name: str,
    skill_desc: str = "",
    category: str = "general",
    module_path: str = "",
    function_name: str = "",
    enabled: bool = True,
) -> str:
    """创建一个 Skill。当用户想添加一个新的 Skill 时使用此工具。

    Args:
        skill_name: Skill 名称（唯一标识，如 "text-stats"）
        skill_desc: Skill 描述
        category: 分类（如 "general", "coding", "analysis"）
        enabled: 是否启用（True/False）

    Returns:
        创建结果，含 pr_key_id 和 skill_id
    """
    from infrastructure.database.repositories.skill_repository import SkillRepository
    from utils.id_generator import generate_skill_id

    repo = SkillRepository()
    skill_id = generate_skill_id(skill_name)
    try:
        config = {"category": category}
        if module_path:
            config["module_path"] = module_path
        if function_name:
            config["function_name"] = function_name
        entity = repo.create(
            skill_id=skill_id,
            skill_name=skill_name,
            skill_desc=skill_desc,
            config_param=json.dumps(config),
            input_json_param="",
            enable_status="1" if enabled else "0",
            del_flag="0",
        )
        if entity:
            return (
                f"Skill '{skill_name}' 创建成功。"
                f"pr_key_id={entity.pr_key_id}, skill_id={skill_id}"
            )
        return f"Skill '{skill_name}' 创建失败"
    except Exception as e:
        return f"创建 Skill 失败: {e}"


@tool
async def list_skills() -> str:
    """列出所有已创建的 Skill。"""
    from infrastructure.database.repositories.skill_repository import SkillRepository

    repo = SkillRepository()
    skills = repo.get_all() or []
    lines = []
    for s in skills:
        status = "启用" if s.get("enable_status") == "1" or s.get("enabled") else "禁用"
        lines.append(
            f"- {s.get('skill_name', '')} "
            f"(pr_key_id={s.get('pr_key_id')}, skill_id={s.get('skill_id', '')}, {status})"
        )
    return f"共 {len(skills)} 个 Skill:\n" + "\n".join(lines)


@tool
async def delete_skill(pr_key_id: str) -> str:
    """删除一个 Skill。

    Args:
        pr_key_id: Skill 的 pr_key_id（从 create_skill 或 list_skills 获取）

    Returns:
        删除结果
    """
    from infrastructure.database.repositories.skill_repository import SkillRepository

    repo = SkillRepository()
    try:
        ok = repo.delete_skill(int(pr_key_id))
        if ok:
            return f"Skill (pr_key_id={pr_key_id}) 删除成功。"
        return f"Skill (pr_key_id={pr_key_id}) 不存在或删除失败。"
    except Exception as e:
        return f"删除失败: {e}"


@tool
async def generate_skill_impl(
    skill_name: str,
    code: str,
    function_name: str = "run",
    skill_desc: str = "",
    category: str = "general",
    enabled: bool = True,
) -> str:
    """从 LLM 生成的代码创建可执行 skill（写入文件 + 注册 module_path）。

    当用户描述了一个 skill 的功能，LLM 生成实现代码后用此工具落盘 + 创建 skill 记录。
    code 写入 domain/skill/generated/<skill_name>.py，module_path 自动设为 domain.skill.generated.<skill_name>。

    Args:
        skill_name: Skill 名称（唯一标识，用作文件名，如 "word-counter"）
        code: Python 实现代码（含 def <function_name>(...): ...）
        function_name: 代码中入口函数名（默认 "run"）
        skill_desc: Skill 描述
        category: 分类
        enabled: 是否启用

    Returns:
        创建结果，含 pr_key_id 和 module_path
    """
    from pathlib import Path
    from infrastructure.database.repositories.skill_repository import SkillRepository
    from utils.id_generator import generate_skill_id

    # 写代码到 generated 目录
    generated_dir = Path(__file__).resolve().parent.parent / "domain" / "skill" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    file_path = generated_dir / f"{skill_name}.py"
    try:
        file_path.write_text(code, encoding="utf-8")
    except Exception as e:
        return f"写入 skill 代码失败: {type(e).__name__}: {e}"

    # 创建 skill 记录（config_param 含 module_path/function_name）
    module_path = f"domain.skill.generated.{skill_name}"
    config = {"category": category, "module_path": module_path, "function_name": function_name}
    repo = SkillRepository()
    skill_id = generate_skill_id(skill_name)
    try:
        entity = repo.create(
            skill_id=skill_id,
            skill_name=skill_name,
            skill_desc=skill_desc,
            config_param=json.dumps(config),
            input_json_param="",
            enable_status="1" if enabled else "0",
            del_flag="0",
        )
        if entity:
            # 刷新 skill registry（与手动 POST /api/admin/skills/create 一致）
            try:
                from domain.skill.registry import reset_skill_registry, get_skill_registry
                reset_skill_registry()
                await get_skill_registry()
            except Exception as e:
                logger.warning(f"[generate_skill_impl] reset_skill_registry 失败: {e}")
            return (
                f"Skill '{skill_name}' 创建成功（含实现代码）。"
                f"pr_key_id={entity.pr_key_id}, module_path={module_path}, function_name={function_name}"
            )
        return f"Skill '{skill_name}' 创建失败"
    except Exception as e:
        return f"创建 Skill 失败: {e}"
