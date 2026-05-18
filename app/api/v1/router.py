from fastapi import APIRouter

from app.api.v1.api_config import router as api_config_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chatwoot import router as chatwoot_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.settings import router as settings_router
from app.api.v1.system_prompts import router as system_prompts_router
from app.api.v1.uploads import router as uploads_router

api_router = APIRouter()
api_router.include_router(api_config_router)
api_router.include_router(auth_router)
api_router.include_router(chatwoot_router)
api_router.include_router(knowledge_router)
api_router.include_router(settings_router)
api_router.include_router(system_prompts_router)
api_router.include_router(uploads_router)
