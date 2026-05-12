from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings

OPENAPI_TAGS = [
    {
        "name": "api-config",
        "description": "API documentation imports, endpoint cataloging, MCP metadata, and AI access controls.",
    },
    {
        "name": "auth",
        "description": "Account registration, login, sessions, email verification, invitations, and password recovery.",
    },
    {
        "name": "settings",
        "description": "Workspace, brand, user profile, member, and role management.",
    },
    {
        "name": "system",
        "description": "Operational health endpoints.",
    },
]


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        summary="Authentication and workspace settings API for Brain Assistant.",
        description=(
            "Brain Assistant backend API for auth, email verification, password reset, "
            "workspace settings, brand settings, and member invitations."
        ),
        version=settings.app_version,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url=settings.openapi_url,
        openapi_tags=OPENAPI_TAGS,
        swagger_ui_parameters={
            "displayRequestDuration": True,
            "persistAuthorization": True,
            "tryItOutEnabled": True,
        },
    )

    if settings.cors_origin_strings:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_strings,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.get("/health", tags=["system"])
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "service": settings.app_name})

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
