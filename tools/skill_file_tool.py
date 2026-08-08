from __future__ import annotations
from langchain_core.tools import tool
from loguru import logger
_reader = None
_current_session_id = None
def set_skill_file_reader(reader) -> None:
    global _reader
    _reader = reader
def get_skill_file_reader():
    return _reader
def set_current_session_id(session_id: str | None) -> None:
    global _current_session_id
    _current_session_id = session_id
def get_current_session_id() -> str | None:
    return _current_session_id
@tool
async def read_file(file_path: str) -> str:
    """Read the content of a file by its file path.
    
    Tries the Skill file system first; if the file is not found there,
    falls back to the sandbox workspace (/mnt/workspace/).
    """
    reader = get_skill_file_reader()
    if reader is not None:
        try:
            content = reader.read_file(file_path)
            logger.info(f"[read_file] skill: {file_path} ({len(content)} chars)")
            return content
        except FileNotFoundError:
            logger.debug(f"[read_file] skill not found: {file_path}, trying sandbox...")
        except Exception as e:
            logger.warning(f"[read_file] skill reader error: {file_path} - {e}")

    # Fallback: try sandbox workspace
    try:
        from tools.sandbox_tools import _get_sandbox
        sandbox = _get_sandbox()
        if sandbox is not None:
            content = sandbox.read_file(file_path)
            logger.info(f"[read_file] sandbox: {file_path} ({len(content)} chars)")
            return content
    except FileNotFoundError:
        logger.warning(f"[read_file] not found anywhere: {file_path}")
        return f"Error: 文件不存在: {file_path}"
    except Exception as e:
        logger.warning(f"[read_file] sandbox error: {file_path} - {e}")
        return f"Error reading file: {e}"

    return "Error: 无法读取文件（Skill 文件系统和沙箱均不可用）"
SKILL_FILE_TOOL_NAME = "read_file"