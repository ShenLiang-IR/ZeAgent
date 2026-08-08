from .auth_routes import router as auth_router
from .admin_routes import router as admin_rbac_router

__all__ = ["auth_router", "admin_rbac_router"]
