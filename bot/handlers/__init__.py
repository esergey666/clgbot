from aiogram import Router

from .admin import router as admin_router
from .label import router as label_router
from .start import router as start_router
from bot.receipts.handlers import router as french_receipt_router


def setup_routers() -> Router:
    router = Router()
    router.include_router(admin_router)
    router.include_router(start_router)
    router.include_router(french_receipt_router)
    router.include_router(label_router)
    return router
