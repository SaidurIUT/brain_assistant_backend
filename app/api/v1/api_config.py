from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ApiServer, User
from app.schemas.api_config import (
    ApiConfiguratorPublic,
    ApiDocumentationImportRequest,
    ApiDocumentationSourcePublic,
    ApiEndpointCreateRequest,
    ApiEndpointPublic,
    ApiEndpointUpdateRequest,
    ApiServerCreateRequest,
    ApiServerDetailPublic,
    ApiServerPublic,
    ApiServerUpdateRequest,
)
from app.schemas.auth import MessageResponse
from app.services.api_config import (
    create_manual_endpoint,
    create_server,
    endpoint_for_server,
    import_api_documentation,
    list_endpoints,
    list_servers,
    list_sources,
    server_for_company,
    update_endpoint,
    update_server,
)
from app.services.auth import audit_event
from app.services.settings import current_company, require_company_admin

router = APIRouter(prefix="/api-config", tags=["api-config"])


def server_public(db: Session, server: ApiServer) -> ApiServerPublic:
    return ApiServerPublic(
        id=server.id,
        name=server.name,
        description=server.description,
        base_url=server.base_url,
        created_at=server.created_at,
        updated_at=server.updated_at,
        source_count=len(list_sources(db, server)),
        endpoint_count=len(list_endpoints(db, server)),
    )


def server_detail_response(db: Session, server: ApiServer) -> ApiServerDetailPublic:
    return ApiServerDetailPublic(
        server=server_public(db, server),
        sources=[ApiDocumentationSourcePublic.model_validate(source) for source in list_sources(db, server)],
        endpoints=[ApiEndpointPublic.model_validate(endpoint) for endpoint in list_endpoints(db, server)],
    )


@router.get("", response_model=ApiConfiguratorPublic)
def get_api_configurator(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiConfiguratorPublic:
    company = current_company(db, current_user, company_id)
    return ApiConfiguratorPublic(servers=[server_public(db, server) for server in list_servers(db, company)])


@router.post("/servers", response_model=ApiServerDetailPublic, status_code=status.HTTP_201_CREATED)
def add_server(
    payload: ApiServerCreateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiServerDetailPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    server = create_server(db, company=company, payload=payload)
    audit_event(
        db,
        event_type="api_server_added",
        request=request,
        user_id=current_user.id,
        metadata={"server_id": str(server.id), "name": server.name, "base_url": server.base_url},
    )
    db.commit()
    db.refresh(server)
    return server_detail_response(db, server)


@router.get("/servers/{server_id}", response_model=ApiServerDetailPublic)
def get_server(
    server_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiServerDetailPublic:
    company = current_company(db, current_user, company_id)
    server = server_for_company(db, company=company, server_id=server_id)
    return server_detail_response(db, server)


@router.patch("/servers/{server_id}", response_model=ApiServerDetailPublic)
def patch_server(
    server_id: UUID,
    payload: ApiServerUpdateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiServerDetailPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    server = update_server(server_for_company(db, company=company, server_id=server_id), payload)
    audit_event(
        db,
        event_type="api_server_updated",
        request=request,
        user_id=current_user.id,
        metadata={"server_id": str(server.id), "name": server.name},
    )
    db.commit()
    db.refresh(server)
    return server_detail_response(db, server)


@router.post("/servers/{server_id}/import", response_model=ApiServerDetailPublic, status_code=status.HTTP_201_CREATED)
def import_documentation(
    server_id: UUID,
    payload: ApiDocumentationImportRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiServerDetailPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    server = server_for_company(db, company=company, server_id=server_id)
    source = import_api_documentation(db, company=company, server=server, payload=payload)
    audit_event(
        db,
        event_type="api_documentation_imported",
        request=request,
        user_id=current_user.id,
        metadata={"server_id": str(server.id), "source_id": str(source.id), "source_url": source.source_url},
    )
    db.commit()
    db.refresh(server)
    return server_detail_response(db, server)


@router.post("/servers/{server_id}/endpoints", response_model=ApiEndpointPublic, status_code=status.HTTP_201_CREATED)
def add_endpoint(
    server_id: UUID,
    payload: ApiEndpointCreateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiEndpointPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    server = server_for_company(db, company=company, server_id=server_id)
    endpoint = create_manual_endpoint(db, company=company, server=server, payload=payload)
    audit_event(
        db,
        event_type="api_endpoint_added",
        request=request,
        user_id=current_user.id,
        metadata={"server_id": str(server.id), "endpoint_id": str(endpoint.id), "method": endpoint.method, "path": endpoint.path},
    )
    db.commit()
    db.refresh(endpoint)
    return ApiEndpointPublic.model_validate(endpoint)


@router.patch("/servers/{server_id}/endpoints/{endpoint_id}", response_model=ApiEndpointPublic)
def patch_endpoint(
    server_id: UUID,
    endpoint_id: UUID,
    payload: ApiEndpointUpdateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiEndpointPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    server = server_for_company(db, company=company, server_id=server_id)
    endpoint = update_endpoint(endpoint_for_server(db, server=server, endpoint_id=endpoint_id), payload)
    audit_event(
        db,
        event_type="api_endpoint_updated",
        request=request,
        user_id=current_user.id,
        metadata={"server_id": str(server.id), "endpoint_id": str(endpoint.id), "ai_access": endpoint.is_accessible_to_ai},
    )
    db.commit()
    db.refresh(endpoint)
    return ApiEndpointPublic.model_validate(endpoint)


@router.delete("/servers/{server_id}/endpoints/{endpoint_id}", response_model=MessageResponse)
def delete_endpoint(
    server_id: UUID,
    endpoint_id: UUID,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    server = server_for_company(db, company=company, server_id=server_id)
    endpoint = endpoint_for_server(db, server=server, endpoint_id=endpoint_id)
    db.delete(endpoint)
    audit_event(
        db,
        event_type="api_endpoint_deleted",
        request=request,
        user_id=current_user.id,
        metadata={"server_id": str(server.id), "endpoint_id": str(endpoint.id)},
    )
    db.commit()
    return MessageResponse(message="API endpoint removed")
