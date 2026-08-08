from .admin import admin_router
from .chat import chat_router_main
from utils.common.auth_dependencies import get_user_id_from_auth_header
__all__ = [
    'admin_router',
    'chat_router_main',
    'get_user_id_from_auth_header'
]