from fastapi import APIRouter
from .session_routes import router as chat_router
from .chat_routes import router as chat_api_router
chat_router_main = APIRouter(prefix="/api", tags=["chat"])
chat_router_main.include_router(chat_router)
chat_router_main.include_router(chat_api_router)
__all__ = ['chat_router_main']