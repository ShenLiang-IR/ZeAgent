"""admin 路由异常处理装饰器（#12 参数化方案）。

统一 except Exception -> logger.error + HTTPException(500)，消除 api/admin/ 126 处手写样板。
HTTPException 透传（不重复包装已有 4xx/422）。

参数化维度（基于 admin 现有 126 处 except 分析）：
- context: 日志/错误上下文（如 "[Menu]", " Agent", " API"）
- detail_with_context: True -> detail=f"{context}: {e}"（21+ 处模式），False -> detail=str(e)（37 处模式）
- exc_info: logger.error 是否含 traceback（默认 True）

迁移示例（agent_manage.py list_agents）：
    # 之前
    @router.get("/list", response_model=AgentListResponse)
    async def list_agents(...):
        try:
            repo = AgentRepository()
            ...
            return AgentListResponse(...)
        except Exception as e:
            logger.error(f" Agent : {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f" Agent : {str(e)}")

    # 之后
    @router.get("/list", response_model=AgentListResponse)
    @handle_admin_errors(" Agent", detail_with_context=True)
    async def list_agents(...):
        repo = AgentRepository()
        ...
        return AgentListResponse(...)

迁移计划（21 文件，126 处）：
1. 先 1 文件试点（agent_manage.py），验证装饰器 + 跑该文件 import
2. 逐文件迁移（每文件改后跑 import + 相关测试）
3. detail 形如 "前缀: {str(e)}"（无 context 前缀）的 21 处 -> detail_with_context=False，context 仅用于 logger
"""
from functools import wraps
from fastapi import HTTPException
from loguru import logger


def handle_admin_errors(context: str = "", *, detail_with_context: bool = False, exc_info: bool = True):
    """admin 路由异常处理装饰器。

    Args:
        context: 日志/错误上下文（如 "[Menu]", " Agent"）。
        detail_with_context: True -> detail=f"{context}: {str(e)}"，False -> detail=str(e)。
        exc_info: logger.error 是否含 traceback。
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise  # 透传已有 HTTPException（4xx/422 等，不包装为 500）
            except Exception as e:
                logger.error(f"{context}: {str(e)}", exc_info=exc_info)
                detail = f"{context}: {str(e)}" if detail_with_context else str(e)
                raise HTTPException(status_code=500, detail=detail)
        return wrapper
    return decorator


def handle_admin_errors_wrap(context: str = "", *, message=None, message_with_context: bool = False, exc_info: bool = True, response_func=None):
    """admin 路由异常处理装饰器（wrap_response 模式）。

    区别于 handle_admin_errors（raise HTTPException），本装饰器 catch 后
    return response_func(None, message, success=False)，用于 menu 等 wrap_response 路由，
    或 mcp 的 api_response 路由（传 response_func=api_response）。

    Args:
        context: 日志/错误上下文（如 "[Menu]"）。
        message: message 模板（如 "查询失败: {e}"），format e=str(e)。优先于 message_with_context。
        message_with_context: True -> message=f"{context}: {e}"，False -> message=str(e)。
        exc_info: logger.error 是否含 traceback（默认 False，匹配 menu 现有无 exc_info）。
        response_func: 响应函数（默认 wrap_response，mcp 传 api_response）。
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                from .base import wrap_response  # 局部 import 避免循环
                resp = response_func or wrap_response
                logger.error(f"{context}: {str(e)}", exc_info=exc_info)
                if message is not None:
                    msg = message.format(e=str(e))
                elif message_with_context:
                    msg = f"{context}: {str(e)}"
                else:
                    msg = str(e)
                return resp(None, message=msg, success=False)
        return wrapper
    return decorator
