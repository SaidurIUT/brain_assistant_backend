from fastapi import APIRouter

from app.api.v1.api_config import router as api_config_router
from app.api.v1.auth import router as auth_router
from app.api.v1.settings import router as settings_router

api_router = APIRouter()
api_router.include_router(api_config_router)
api_router.include_router(auth_router)
api_router.include_router(settings_router)
