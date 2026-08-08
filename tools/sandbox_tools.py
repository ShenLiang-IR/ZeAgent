from __future__ import annotations
import re
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from loguru import logger
from pathlib import Path
from infrastructure.sandbox.path_mapping import truncate_output, reject_path_traversal


class WriteFileInput(BaseModel):
    file_path: str = Field(..., description="写入的文件路径，如 result.txt 或 dir/output.md")
    content: str = Field(..., description="要写入的文件内容")
    append: bool = Field(default=False, description="是否追加模式，默认覆盖写入")


class ListDirInput(BaseModel):
    path: str = Field(..., description="要列出的目录路径")
    max_depth: int = Field(default=2, description="最大递归深度")


class BashInput(BaseModel):
    command: str = Field(..., description="要执行的 bash 命令")


def _get_sandbox():
    try:
        from infrastructure.sandbox import get_sandbox_provider
        from tools.skill_file_tool import get_current_session_id
        provider = get_sandbox_provider()
        if provider is None:
            return None
        session_id = get_current_session_id()
        return provider.acquire(session_id=session_id)
    except Exception as e:
        logger.debug(f"[sandbox_tools] _get_sandbox failed: {e}")
        return None


def _get_local_fallback_root() -> Path:
    """降级写入的本地可写根目录（沙箱不可用时收敛写位置，防越界）。

    优先读 config ``sandbox.local_fallback_root``；未配置则默认
    ``<项目根>/data/sandbox_fallback``。
    """
    try:
        from utils.config import get_config
        root_cfg = get_config("sandbox.local_fallback_root", None)
        root = Path(root_cfg) if root_cfg else (
            Path(__file__).resolve().parent.parent / "data" / "sandbox_fallback"
        )
    except Exception:
        root = Path(__file__).resolve().parent.parent / "data" / "sandbox_fallback"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _resolve_local_safe(file_path: str) -> Path:
    """降级路径解析：拒绝路径遍历，绝对路径须在可写根内，相对路径拼到根下。

    Raises:
        ValueError: 路径含 ``..``（路径遍历）
        PermissionError: 绝对路径超出可写根
    """
    reject_path_traversal(file_path)
    root = _get_local_fallback_root()
    p = Path(file_path)
    if p.is_absolute():
        resolved = p.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise PermissionError(f"绝对路径超出可写根，拒绝写入: {file_path}")
        return resolved
    return (root / file_path).resolve()


def _write_file_impl(file_path: str, content: str, append: bool = False) -> str:
    """Write content to a file. Works with or without sandbox.
    
    沙箱模式下优先写沙箱；若路径未映射（ValueError）或其他沙箱异常，
    自动降级为本地文件写入，确保 Agent 总能写文件。
    """
    sandbox = _get_sandbox()
    sandbox_ok = False
    if sandbox is not None:
        try:
            sandbox.write_file(file_path, content, append=append)
            mode = "append" if append else "write"
            logger.info(f"[write_file] sandbox {mode}: {file_path} ({len(content)} chars)")
            sandbox_ok = True
        except (ValueError, PermissionError) as e:
            logger.info(f"[write_file] sandbox fallback: {file_path} - {e}，降级为本地写入")
        except Exception as e:
            logger.warning(f"[write_file] sandbox error, fallback to local: {file_path} - {e}")
    if sandbox_ok:
        return f"OK: content written to {file_path}"
    try:
        p = _resolve_local_safe(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(p, mode, encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[write_file] local {mode}: {file_path} ({len(content)} chars)")
        return f"OK: content written to {file_path}"
    except (ValueError, PermissionError) as e:
        logger.warning(f"[write_file] local 路径被拒: {file_path} - {e}")
        return f"Error: {e}"
    except Exception as e:
        logger.error(f"[write_file] local error: {file_path} - {e}")
        return f"Error writing file: {e}"


def _list_dir_impl(path: str, max_depth: int = 2) -> str:
    """List directory contents. Works with or without sandbox.
    
    沙箱模式下优先读沙箱；若路径未映射或沙箱异常，自动降级为本地目录读取。
    """
    sandbox = _get_sandbox()
    sandbox_ok = False
    sandbox_entries = None
    if sandbox is not None:
        try:
            sandbox_entries = sandbox.list_dir(path, min(max_depth, 5))
            sandbox_ok = True
        except (ValueError, FileNotFoundError, PermissionError) as e:
            logger.info(f"[list_dir] sandbox fallback: {path} - {e}，降级为本地读取")
        except Exception as e:
            logger.warning(f"[list_dir] sandbox error, fallback to local: {path} - {e}")
    if sandbox_ok and sandbox_entries is not None:
        if not sandbox_entries:
            return f"Empty directory: {path}"
        logger.info(f"[list_dir] sandbox: {path} ({len(sandbox_entries)} entries)")
        return truncate_output("\n".join(sandbox_entries), 10000)
    try:
        p = _resolve_local_safe(path)
        if not p.is_dir():
            return f"Error: not a directory: {path}"
        entries = []
        _walk_local(p, p, entries, min(max_depth, 5), 0)
        if not entries:
            return f"Empty directory: {path}"
        return truncate_output("\n".join(entries), 10000)
    except (ValueError, PermissionError) as e:
        logger.warning(f"[list_dir] local 路径被拒: {path} - {e}")
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


_BASH_MAX_COMMAND_LEN = 2000
_BASH_DANGEROUS_PATTERNS = [
    re.compile(r'\brm\s+-[rfRF]+\s+/'),                # rm -rf /
    re.compile(r'\bmkfs\b', re.IGNORECASE),
    re.compile(r'\bdd\b.*\bof=/dev/', re.IGNORECASE),  # dd ... of=/dev/...
    re.compile(r'\bformat\b', re.IGNORECASE),
    re.compile(r'\bshutdown\b', re.IGNORECASE),
    re.compile(r'\breboot\b', re.IGNORECASE),
    re.compile(r'\bhalt\b', re.IGNORECASE),
    re.compile(r'\bpoweroff\b', re.IGNORECASE),
    re.compile(r':\(\)\s*\{'),                          # fork bomb :(){ ... }
    re.compile(r'\bdel\s+/[sS]\b', re.IGNORECASE),      # Windows del /s
    re.compile(r'\brdisk\b', re.IGNORECASE),
]


def _validate_bash_command(command: str, whitelist: list[str] | None = None) -> str | None:
    """校验 bash 命令安全性，返回错误消息或 None（通过）。

    黑名单非根治方案（白名单难维护），但能拦截明显的破坏性命令。
    根治需容器级隔离 + cgroup 资源限制，作为后续迭代。
    """
    if len(command) > _BASH_MAX_COMMAND_LEN:
        return f"命令长度超限（>{_BASH_MAX_COMMAND_LEN} 字符）"
    for pat in _BASH_DANGEROUS_PATTERNS:
        if pat.search(command):
            return "命令含危险模式，拒绝执行"
    # 命令白名单（若配置 sandbox.bash_command_whitelist）：首词需在白名单
    if whitelist and isinstance(whitelist, list):
        first_word = command.strip().split()[0] if command.strip() else ""
        if first_word and first_word not in whitelist:
            return f"命令 '{first_word}' 不在白名单，拒绝执行"
    return None


def _bash_impl(command: str) -> str:
    """Execute a bash/shell command (sandbox must be enabled)."""
    sandbox = _get_sandbox()
    if sandbox is None:
        return "Error: Sandbox not initialized."
    from utils.config import get_config
    if not get_config("sandbox.allow_bash", False):
        return "Error: Bash execution disabled. Enable sandbox.allow_bash=true"
    whitelist = get_config("sandbox.bash_command_whitelist", None)
    err = _validate_bash_command(command, whitelist=whitelist)
    if err:
        logger.warning(f"[bash] 命令被拒: {command[:100]}... - {err}")
        return f"Error: {err}"
    try:
        output = sandbox.execute_command(command)
        logger.info(f"[bash] executed: {command[:100]}...")
        return truncate_output(output, 20000)
    except Exception as e:
        return f"Error: {e}"


def _walk_local(root: Path, current: Path, entries: list, max_depth: int, depth: int):
    if depth > max_depth:
        return
    try:
        items = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    except PermissionError:
        return
    for item in items:
        if item.name.startswith("."):
            continue
        rel = item.relative_to(root)
        entries.append(str(rel))
        if item.is_dir():
            _walk_local(root, item, entries, max_depth, depth + 1)


# 同步 StructuredTool（兼容 LangGraph create_agent）
write_file = StructuredTool.from_function(
    func=_write_file_impl,
    name="write_file",
    description="写文件。参数: file_path(必填)文件路径, content(必填)文件内容, append(可选)是否追加",
    args_schema=WriteFileInput,
)

list_dir = StructuredTool.from_function(
    func=_list_dir_impl,
    name="list_dir",
    description="列目录。参数: path(必填)目录路径, max_depth(可选,默认2)递归深度",
    args_schema=ListDirInput,
)

bash = StructuredTool.from_function(
    func=_bash_impl,
    name="bash",
    description="执行bash命令（需开启沙箱）",
    args_schema=BashInput,
)


def get_sandbox_tools() -> list:
    tools = [write_file, list_dir]
    try:
        from utils.config import get_config
        if get_config("sandbox.allow_bash", False):
            tools.append(bash)
    except Exception:
        pass
    return tools
