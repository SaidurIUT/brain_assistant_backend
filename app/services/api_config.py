import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import ApiDocumentationSource, ApiEndpoint, ApiServer, Company
from app.schemas.api_config import (
    ApiDocumentationImportRequest,
    ApiEndpointCreateRequest,
    ApiEndpointUpdateRequest,
    ApiServerCreateRequest,
    ApiServerUpdateRequest,
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def list_servers(db: Session, company: Company) -> list[ApiServer]:
    return list(
        db.scalars(
            select(ApiServer)
            .where(ApiServer.company_id == company.id)
            .order_by(ApiServer.created_at.desc())
        )
    )


def server_for_company(db: Session, *, company: Company, server_id) -> ApiServer:
    server = db.get(ApiServer, server_id)
    if server is None or server.company_id != company.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API server not found")
    return server


def create_server(db: Session, *, company: Company, payload: ApiServerCreateRequest) -> ApiServer:
    server = ApiServer(
        company_id=company.id,
        name=payload.name,
        description=payload.description,
        base_url=payload.base_url,
    )
    db.add(server)
    db.flush()
    if payload.source_url:
        import_api_documentation(
            db,
            company=company,
            server=server,
            payload=ApiDocumentationImportRequest(
                source_url=payload.source_url,
                source_type=payload.source_type,
                base_url=payload.base_url,
            ),
        )
    elif payload.document_text:
        import_api_documentation(
            db,
            company=company,
            server=server,
            payload=ApiDocumentationImportRequest(
                source_url="",
                source_type=payload.source_type,
                base_url=payload.base_url,
                document_text=payload.document_text,
                document_name=payload.document_name,
            ),
        )
    return server


def update_server(server: ApiServer, payload: ApiServerUpdateRequest) -> ApiServer:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(server, field, value)
    return server


def list_sources(db: Session, server: ApiServer) -> list[ApiDocumentationSource]:
    return list(
        db.scalars(
            select(ApiDocumentationSource)
            .where(ApiDocumentationSource.server_id == server.id)
            .order_by(ApiDocumentationSource.created_at.desc())
        )
    )


def list_endpoints(db: Session, server: ApiServer) -> list[ApiEndpoint]:
    return list(
        db.scalars(
            select(ApiEndpoint)
            .where(ApiEndpoint.server_id == server.id)
            .order_by(ApiEndpoint.path.asc(), ApiEndpoint.method.asc())
        )
    )


def import_api_documentation(
    db: Session,
    *,
    company: Company,
    server: ApiServer,
    payload: ApiDocumentationImportRequest,
) -> ApiDocumentationSource:
    if payload.document_text:
        document = parse_document_text(payload.document_text)
    elif payload.source_url:
        document = fetch_api_document(payload.source_url)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a documentation URL or upload an API documentation file",
        )
    detected_base_url = base_url_for_document(document)
    source_base_url = payload.base_url or server.base_url or detected_base_url
    if payload.base_url or (source_base_url and not server.base_url):
        server.base_url = source_base_url
    source = ApiDocumentationSource(
        company_id=company.id,
        server_id=server.id,
        source_type=detect_source_type(document, payload.source_type),
        source_url=payload.source_url or payload.document_name or "Uploaded API document",
        title=str(document.get("info", {}).get("title") or "Imported API"),
        version=str(document.get("info", {}).get("version") or ""),
        base_url=source_base_url,
        status="active",
        raw_document=document,
    )
    db.add(source)
    db.flush()

    endpoint_payloads = endpoints_from_document(document)
    for endpoint_payload in endpoint_payloads:
        upsert_endpoint(db, company=company, server=server, source=source, payload=endpoint_payload)

    source.status = "active" if endpoint_payloads else "no_endpoints_found"
    db.flush()
    return source


def create_manual_endpoint(
    db: Session,
    *,
    company: Company,
    server: ApiServer,
    payload: ApiEndpointCreateRequest,
) -> ApiEndpoint:
    return upsert_endpoint(db, company=company, server=server, source=None, payload=payload)


def update_endpoint(endpoint: ApiEndpoint, payload: ApiEndpointUpdateRequest) -> ApiEndpoint:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(endpoint, field, value)
    return endpoint


def endpoint_for_company(db: Session, *, company: Company, endpoint_id) -> ApiEndpoint:
    endpoint = db.get(ApiEndpoint, endpoint_id)
    if endpoint is None or endpoint.company_id != company.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API endpoint not found")
    return endpoint


def endpoint_for_server(db: Session, *, server: ApiServer, endpoint_id) -> ApiEndpoint:
    endpoint = db.get(ApiEndpoint, endpoint_id)
    if endpoint is None or endpoint.server_id != server.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API endpoint not found")
    return endpoint


def upsert_endpoint(
    db: Session,
    *,
    company: Company,
    server: ApiServer,
    source: ApiDocumentationSource | None,
    payload: ApiEndpointCreateRequest,
) -> ApiEndpoint:
    method = payload.method.upper()
    existing = db.scalar(
        select(ApiEndpoint).where(
            ApiEndpoint.server_id == server.id,
            ApiEndpoint.method == method,
            ApiEndpoint.path == payload.path,
        )
    )
    endpoint = existing or ApiEndpoint(company_id=company.id, server_id=server.id, method=method, path=payload.path)
    endpoint.source_id = source.id if source else endpoint.source_id
    endpoint.summary = payload.summary
    endpoint.description = payload.description
    endpoint.operation_id = payload.operation_id
    endpoint.auth_required = payload.auth_required
    endpoint.auth_type = payload.auth_type
    endpoint.parameters = payload.parameters
    endpoint.request_body = payload.request_body
    endpoint.responses = payload.responses
    if existing is None:
        endpoint.is_accessible_to_ai = payload.is_accessible_to_ai
        db.add(endpoint)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An endpoint with this method and path already exists",
        ) from exc
    return endpoint


def fetch_api_document(source_url: str) -> dict[str, Any]:
    request = Request(source_url, headers={"User-Agent": "BrainAssistantApiConfigurator/0.1"})
    try:
        with urlopen(request, timeout=10) as response:
            content = response.read(MAX_DOCUMENT_BYTES + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not fetch API documentation URL",
        ) from exc

    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="API documentation is too large")
    text = content.decode("utf-8")
    return parse_document_text(text)


def parse_document_text(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="API documentation must be valid JSON or YAML",
            ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API documentation must be an object")
    if "paths" not in parsed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API documentation must include paths")
    return parsed


def detect_source_type(document: dict[str, Any], fallback: str) -> str:
    if "openapi" in document:
        return "openapi"
    if "swagger" in document:
        return "swagger"
    return fallback or "api_documentation"


def base_url_for_document(document: dict[str, Any]) -> str:
    servers = document.get("servers")
    if isinstance(servers, list) and servers:
        first_server = servers[0]
        if isinstance(first_server, dict):
            return str(first_server.get("url") or "")
    host = document.get("host")
    if host:
        schemes = document.get("schemes") if isinstance(document.get("schemes"), list) else []
        scheme = schemes[0] if schemes else "https"
        base_path = document.get("basePath") or ""
        return f"{scheme}://{host}{base_path}"
    return ""


def endpoints_from_document(document: dict[str, Any]) -> list[ApiEndpointCreateRequest]:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return []
    security_schemes = security_scheme_names(document)
    root_security = document.get("security")
    endpoints: list[ApiEndpointCreateRequest] = []

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_parameters = path_item.get("parameters") if isinstance(path_item.get("parameters"), list) else []
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_security = operation.get("security", root_security)
            auth_required = bool(operation_security)
            auth_type = auth_type_from_security(operation_security, security_schemes) if auth_required else ""
            parameters = [*path_parameters, *(operation.get("parameters") if isinstance(operation.get("parameters"), list) else [])]
            endpoints.append(
                ApiEndpointCreateRequest(
                    method=method.upper(),
                    path=str(path),
                    summary=str(operation.get("summary") or ""),
                    description=str(operation.get("description") or ""),
                    operation_id=str(operation.get("operationId") or ""),
                    auth_required=auth_required,
                    auth_type=auth_type,
                    parameters=parameters,
                    request_body=request_body_from_operation(operation),
                    responses=operation.get("responses") if isinstance(operation.get("responses"), dict) else {},
                    is_accessible_to_ai=False,
                )
            )
    return endpoints


def security_scheme_names(document: dict[str, Any]) -> dict[str, str]:
    components = document.get("components") if isinstance(document.get("components"), dict) else {}
    schemes = components.get("securitySchemes") if isinstance(components.get("securitySchemes"), dict) else {}
    if not schemes and isinstance(document.get("securityDefinitions"), dict):
        schemes = document["securityDefinitions"]
    names: dict[str, str] = {}
    for name, scheme in schemes.items():
        if isinstance(scheme, dict):
            scheme_type = scheme.get("type") or scheme.get("scheme") or "auth"
            names[str(name)] = str(scheme_type)
    return names


def auth_type_from_security(security: Any, scheme_names: dict[str, str]) -> str:
    if not isinstance(security, list):
        return "auth"
    names: list[str] = []
    for requirement in security:
        if isinstance(requirement, dict):
            names.extend(str(name) for name in requirement.keys())
    if not names:
        return "auth"
    return ", ".join(f"{name} ({scheme_names.get(name, 'auth')})" for name in names)


def request_body_from_operation(operation: dict[str, Any]) -> dict[str, Any]:
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        return request_body
    body_parameters = [
        parameter
        for parameter in operation.get("parameters", [])
        if isinstance(parameter, dict) and parameter.get("in") == "body"
    ]
    if body_parameters:
        return {"parameters": body_parameters}
    return {}
