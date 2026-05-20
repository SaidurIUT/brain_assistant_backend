from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ExternalSourceConnection, ExternalSourceItem, User
from app.schemas.auth import MessageResponse
from app.schemas.external_sources import (
    ExternalSourceConnectionPublic,
    ExternalSourceFolderPublic,
    ExternalSourceFolderSelectionRequest,
    ExternalSourceItemPublic,
    ExternalSourceOAuthStartRequest,
    ExternalSourceOAuthStartResponse,
    ExternalSourceSyncRunPublic,
    ProviderFolderPublic,
)
from app.services.auth import audit_event
from app.services.external_sources import (
    connection_for_company,
    create_oauth_start,
    create_sync_run,
    ensure_provider,
    external_rag_doc_id,
    frontend_redirect,
    list_connections_for_company,
    list_items,
    list_provider_folders,
    list_sync_runs,
    provider_label,
    replace_selected_folders,
    complete_oauth_callback,
)
from app.services import rag_service
from app.services.jobs import enqueue_background_job
from app.services.settings import current_company, require_company_admin

router = APIRouter(prefix="/external-sources", tags=["external-sources"])


def connection_public(record: ExternalSourceConnection) -> ExternalSourceConnectionPublic:
    latest = sorted(record.sync_runs, key=lambda run: run.created_at, reverse=True)[0] if record.sync_runs else None
    return ExternalSourceConnectionPublic.model_validate(
        {
            **record.__dict__,
            "selected_folder_count": len(record.folders),
            "latest_sync_run": latest,
        }
    )


def item_public(record: ExternalSourceItem) -> ExternalSourceItemPublic:
    knowledge_document = record.knowledge_document
    return ExternalSourceItemPublic.model_validate(
        {
            **record.__dict__,
            "extraction_status": knowledge_document.status if knowledge_document else None,
            "extracted_char_count": knowledge_document.char_count if knowledge_document else None,
            "extraction_error": knowledge_document.error_message if knowledge_document else None,
        }
    )


def queue_sync_job(db: Session, connection: ExternalSourceConnection, trigger: str):
    sync_run, background_job = create_sync_run(db, connection=connection, trigger=trigger)
    db.commit()
    try:
        task = enqueue_background_job(background_job.id)
        background_job.celery_task_id = task.id or ""
        db.commit()
    except Exception as exc:
        sync_run.status = "failed"
        sync_run.error_message = f"Could not enqueue external source sync: {exc}"[:1000]
        background_job.status = "failed"
        background_job.error_message = sync_run.error_message
        db.commit()
    db.refresh(sync_run)
    return sync_run


@router.post("/oauth/{provider}/start", response_model=ExternalSourceOAuthStartResponse)
def start_external_source_oauth(
    provider: str,
    payload: ExternalSourceOAuthStartRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExternalSourceOAuthStartResponse:
    provider = ensure_provider(provider)
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    auth_url = create_oauth_start(
        db,
        provider=provider,
        company=company,
        user=current_user,
        redirect_path=payload.redirect_path,
    )
    audit_event(
        db,
        event_type="external_source_oauth_started",
        request=request,
        user_id=current_user.id,
        metadata={"provider": provider, "company_id": str(company.id)},
    )
    db.commit()
    return ExternalSourceOAuthStartResponse(auth_url=auth_url)


@router.get("/oauth/{provider}/callback")
def complete_external_source_oauth(
    provider: str,
    state: str = "",
    code: str = "",
    error: str = "",
    db: Session = Depends(get_db),
) -> RedirectResponse:
    provider = ensure_provider(provider)
    if error:
        return RedirectResponse(
            frontend_redirect(
                "/dashboard/data-sources",
                {"external_source": provider, "connected": "0", "error": error},
            )
        )
    if not state or not code:
        return RedirectResponse(
            frontend_redirect(
                "/dashboard/data-sources",
                {"external_source": provider, "connected": "0", "error": "missing_oauth_response"},
            )
        )
    try:
        connection, redirect_path = complete_oauth_callback(db, provider=provider, state=state, code=code)
        db.commit()
    except Exception as exc:
        db.rollback()
        message = str(exc) or exc.__class__.__name__
        return RedirectResponse(
            frontend_redirect(
                "/dashboard/data-sources",
                {"external_source": provider, "connected": "0", "error": message[:120]},
            )
        )
    return RedirectResponse(
        frontend_redirect(
            redirect_path,
            {
                "external_source": provider,
                "connected": "1",
                "connection_id": str(connection.id),
            },
        )
    )


@router.get("/connections", response_model=list[ExternalSourceConnectionPublic])
def list_external_source_connections(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExternalSourceConnectionPublic]:
    company = current_company(db, current_user, company_id)
    return [connection_public(record) for record in list_connections_for_company(db, company_id=company.id)]


@router.get("/connections/{connection_id}/provider-folders", response_model=list[ProviderFolderPublic])
def browse_external_source_folders(
    connection_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProviderFolderPublic]:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    connection = connection_for_company(db, company_id=company.id, connection_id=connection_id)
    try:
        folders = list_provider_folders(connection)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc) or "Could not load folders") from exc
    return [ProviderFolderPublic.model_validate(folder.__dict__) for folder in folders]


@router.get("/connections/{connection_id}/folders", response_model=list[ExternalSourceFolderPublic])
def list_selected_external_source_folders(
    connection_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExternalSourceFolderPublic]:
    company = current_company(db, current_user, company_id)
    connection = connection_for_company(db, company_id=company.id, connection_id=connection_id)
    return [ExternalSourceFolderPublic.model_validate(folder) for folder in connection.folders]


@router.put("/connections/{connection_id}/folders", response_model=list[ExternalSourceFolderPublic])
def update_selected_external_source_folders(
    connection_id: UUID,
    payload: ExternalSourceFolderSelectionRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExternalSourceFolderPublic]:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    connection = connection_for_company(db, company_id=company.id, connection_id=connection_id)
    folders = replace_selected_folders(
        db,
        connection=connection,
        folders=[folder.model_dump() for folder in payload.folders],
    )
    audit_event(
        db,
        event_type="external_source_folders_updated",
        request=request,
        user_id=current_user.id,
        metadata={"connection_id": str(connection.id), "folder_count": len(folders)},
    )
    db.commit()
    db.refresh(connection)
    if folders:
        queue_sync_job(db, connection, "initial")
    return [ExternalSourceFolderPublic.model_validate(folder) for folder in folders]


@router.post("/connections/{connection_id}/sync", response_model=ExternalSourceSyncRunPublic)
def sync_external_source_connection(
    connection_id: UUID,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExternalSourceSyncRunPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    connection = connection_for_company(db, company_id=company.id, connection_id=connection_id)
    if not connection.folders:
        raise HTTPException(status_code=400, detail=f"Select {provider_label(connection.provider)} folders first")
    sync_run = queue_sync_job(db, connection, "manual")
    audit_event(
        db,
        event_type="external_source_sync_requested",
        request=request,
        user_id=current_user.id,
        metadata={"connection_id": str(connection.id), "sync_run_id": str(sync_run.id)},
    )
    db.commit()
    return ExternalSourceSyncRunPublic.model_validate(sync_run)


@router.get("/connections/{connection_id}/sync-runs", response_model=list[ExternalSourceSyncRunPublic])
def list_external_source_sync_runs(
    connection_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExternalSourceSyncRunPublic]:
    company = current_company(db, current_user, company_id)
    connection = connection_for_company(db, company_id=company.id, connection_id=connection_id)
    return [ExternalSourceSyncRunPublic.model_validate(run) for run in list_sync_runs(db, connection=connection)]


@router.get("/connections/{connection_id}/items", response_model=list[ExternalSourceItemPublic])
def list_external_source_items(
    connection_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExternalSourceItemPublic]:
    company = current_company(db, current_user, company_id)
    connection = connection_for_company(db, company_id=company.id, connection_id=connection_id)
    return [item_public(item) for item in list_items(db, connection=connection)]


@router.delete("/connections/{connection_id}", response_model=MessageResponse)
def delete_external_source_connection(
    connection_id: UUID,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    connection = connection_for_company(db, company_id=company.id, connection_id=connection_id)
    for item in list_items(db, connection=connection):
        if item.knowledge_document_id:
            rag_service.sync_delete_document(external_rag_doc_id(item), company.id)
            if item.knowledge_document is not None:
                db.delete(item.knowledge_document)
    db.delete(connection)
    audit_event(
        db,
        event_type="external_source_connection_deleted",
        request=request,
        user_id=current_user.id,
        metadata={"connection_id": str(connection_id)},
    )
    db.commit()
    return MessageResponse(message="External source connection removed")
