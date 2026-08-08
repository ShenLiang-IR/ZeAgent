from loguru import logger
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
@dataclass
class CommandResult:
    is_command: bool
    command: Optional[str] = None
    success: bool = False
    message: str = ""
    data: Optional[Dict[str, Any]] = None
SUPPORTED_COMMANDS = {
    "/clear": "",
    "/clear_all": "",
    "/help": "",
    "/stats": "",
}
def parse_command(user_input: str) -> Tuple[bool, Optional[str], str]:
    if not user_input:
        return False, None, ""
    text = user_input.strip()
    if not text.startswith("/"):
        return False, None, text
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    remaining = parts[1] if len(parts) > 1 else ""
    if command in SUPPORTED_COMMANDS:
        return True, command, remaining
    return False, None, text
async def handle_clear_command(
    session_id: str,
    user_id: Optional[str] = None
) -> CommandResult:
    try:
        from memory import get_memory_manager
        from infrastructure.database.repositories.chat_repository import ChatRepository
        memory_manager = get_memory_manager()
        memory_deleted = 0
        if memory_manager:
            memory_deleted = await memory_manager.clear_session_memories(session_id)
        message_deleted = 0
        if user_id:
            chat_db = ChatRepository()
            message_deleted = chat_db.delete_messages_by_session(user_id, session_id)
        logger.info(
            f"[Command] /clear  | "
            f"user_id={user_id}, session_id={session_id}, memory_deleted={memory_deleted}, message_deleted={message_deleted}"
        )
        total_deleted = memory_deleted + message_deleted
        return CommandResult(
            is_command=True,
            command="/clear",
            success=True,
            message=f"已清空 {memory_deleted} 条记忆和 {message_deleted} 条消息",
            data={"memory_deleted": memory_deleted, "message_deleted": message_deleted, "total_deleted": total_deleted}
        )
    except Exception as e:
        logger.error(f"[Command] /clear : {e}")
        return CommandResult(
            is_command=True,
            command="/clear",
            success=False,
            message=f"命令执行失败: {str(e)}"
        )
async def handle_clear_all_command(
    session_id: str,
    user_id: Optional[str] = None
) -> CommandResult:
    try:
        from memory import get_memory_manager
        from infrastructure.database.repositories.chat_repository import ChatRepository
        if not user_id:
            return CommandResult(
                is_command=True,
                command="/clear_all",
                success=False,
                message="未提供用户ID，无法清空"
            )
        memory_manager = get_memory_manager()
        memory_deleted = await memory_manager.clear_user_memories(user_id)
        chat_db = ChatRepository()
        message_deleted = chat_db.delete_all_messages_by_user(user_id)
        logger.info(
            f"[Command] /clear_all  | "
            f"user_id={user_id}, memory_deleted={memory_deleted}, message_deleted={message_deleted}"
        )
        return CommandResult(
            is_command=True,
            command="/clear_all",
            success=True,
            message=f"{memory_deleted} {message_deleted} \n\n⚠️ ",
            data={"memory_deleted": memory_deleted, "message_deleted": message_deleted}
        )
    except Exception as e:
        logger.error(f"[Command] /clear_all : {e}")
        return CommandResult(
            is_command=True,
            command="/clear_all",
            success=False,
            message=f"命令执行失败: {str(e)}"
        )
async def handle_help_command() -> CommandResult:
    help_text = "## \n\n"
    for cmd, desc in SUPPORTED_COMMANDS.items():
        help_text += f"- **{cmd}** - {desc}\n"
    help_text += "\n AI "
    return CommandResult(
        is_command=True,
        command="/help",
        success=True,
        message=help_text
    )
async def handle_stats_command(
    session_id: str,
    user_id: Optional[str] = None
) -> CommandResult:
    try:
        from memory import get_memory_manager
        memory_manager = get_memory_manager()
        if not memory_manager:
            return CommandResult(
                is_command=True,
                command="/stats",
                success=False,
                message="记忆系统未初始化"
            )
        stats = await memory_manager.get_stats()
        stats_text = "## \n\n"
        stats_text += f"- ****: {stats['immediate']['count']}/{stats['immediate']['max_size']}\n"
        stats_text += f"- ****: {stats['short_term']['count']}/{stats['short_term']['max_size']} (TTL: {stats['short_term']['ttl_hours']})\n"
        stats_text += f"- ****: {stats['long_term']['count']}/{stats['long_term'].get('max_size', '∞')}\n"
        stats_text += f"- ****: {stats['total']} \n"
        if stats['long_term'].get('storage_backend'):
            stats_text += f"- ****: {stats['long_term']['storage_backend']}\n"
        if stats['long_term'].get('vector_backend'):
            stats_text += f"- ****: {stats['long_term']['vector_backend']}\n"
        return CommandResult(
            is_command=True,
            command="/stats",
            success=True,
            message=stats_text,
            data=stats
        )
    except Exception as e:
        logger.error(f"[Command] /stats : {e}")
        return CommandResult(
            is_command=True,
            command="/stats",
            success=False,
            message=f"命令执行失败: {str(e)}"
        )
async def process_command(
    user_input: str,
    session_id: str,
    user_id: Optional[str] = None
) -> CommandResult:
    is_command, command, remaining = parse_command(user_input)
    if not is_command:
        return CommandResult(is_command=False, message=user_input)
    logger.info(f"[Command] : {command} | session_id={session_id}")
    if command == "/clear":
        return await handle_clear_command(session_id, user_id)
    elif command == "/clear_all":
        return await handle_clear_all_command(session_id, user_id)
    elif command == "/help":
        return await handle_help_command()
    elif command == "/stats":
        return await handle_stats_command(session_id, user_id)
    else:
        return CommandResult(
            is_command=True,
            command=command,
            success=False,
            message=f"未知命令: {command}\n输入 /help 查看可用命令"
        )