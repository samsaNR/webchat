from aiogram import Router

from .admin import router as admin_router
from .user import router as user_router


def build_root_router() -> Router:
    root = Router(name="root")
    # Admin router first so admin-only handlers match before user fallbacks.
    root.include_router(admin_router)
    root.include_router(user_router)
    return root
