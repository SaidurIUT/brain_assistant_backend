from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.datetime import utc_now
from app.core.encryption import decrypt_secret, encrypt_secret
from app.models import (
    BackgroundJob,
    Company,
    ExternalSourceConnection,
    ExternalSourceFolder,
    ExternalSourceItem,
    ExternalSourceOAuthState,
    ExternalSourceSyncRun,
    KnowledgeDocument,
    User,
)
from app.services import rag_service
from app.services.document_extraction import DocumentExtractionError, extract_document_text
from app.services.external_provider_clients import (
    GOOGLE_DRIVE,
    ONEDRIVE,
    ExternalProviderError,
    ProviderFile,
    ProviderFolder,
    exported_filename,
    is_supported_file,
    provider_client,
)
from app.services.jobs import (
    EXTERNAL_SOURCE_SYNC,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_INGESTING,
    JOB_PROCESSING,
    JOB_QUEUED,
)

PROVIDERS = {GOOGLE_DRIVE, ONEDRIVE}
MANAGE_REDIRECT_PATH = "/dashboard/data-sources"

GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/drive.readonly",
]
MICROSOFT_SCOPES = ["offline_access", "User.Read", "Files.Read"]


def ensure_provider(provider: str) -> str:
    if provider not in PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External source provider not found")
    return provider


def create_oauth_start(
    db: Session,
    *,
    provider: str,
    company: Company,
    user: User,
    redirect_path: str,
) -> str:
    provider = ensure_provider(provider)
    ensure_provider_configured(provider)
    state = token_urlsafe(32)
    db.add(
        ExternalSourceOAuthState(
            state_hash=hash_state(state),
            provider=provider,
            company_id=company.id,
            user_id=user.id,
            redirect_path=safe_redirect_path(redirect_path),
            expires_at=utc_now() + timedelta(minutes=10),
        )
    )
    db.flush()
    return oauth_authorization_url(provider, state)


def oauth_authorization_url(provider: str, state: str) -> str:
    if provider == GOOGLE_DRIVE:
        params = {
            "client_id": settings.google_oauth_client_id,
            "redirect_uri": oauth_redirect_uri(provider),
            "response_type": "code",
            "scope": " ".join(GOOGLE_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    params = {
        "client_id": settings.microsoft_oauth_client_id,
        "redirect_uri": oauth_redirect_uri(provider),
        "response_type": "code",
        "response_mode": "query",
        "scope": " ".join(MICROSOFT_SCOPES),
        "state": state,
    }
    tenant = settings.microsoft_oauth_tenant or "common"
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}"


def complete_oauth_callback(
    db: Session,
    *,
    provider: str,
    state: str,
    code: str,
) -> tuple[ExternalSourceConnection, str]:
    provider = ensure_provider(provider)
    oauth_state = consume_oauth_state(db, provider=provider, state=state)
    token_payload = exchange_authorization_code(provider, code)
    profile = fetch_provider_profile(provider, token_payload["access_token"])
    connection = upsert_connection_from_oauth(
        db,
        provider=provider,
        company_id=oauth_state.company_id,
        user_id=oauth_state.user_id,
        token_payload=token_payload,
        account_email=profile["email"],
        account_name=profile["name"],
    )
    return connection, oauth_state.redirect_path


def consume_oauth_state(db: Session, *, provider: str, state: str) -> ExternalSourceOAuthState:
    record = db.scalar(
        select(ExternalSourceOAuthState).where(ExternalSourceOAuthState.state_hash == hash_state(state))
    )
    if record is None or record.provider != provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth session expired")
    if record.consumed_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth session was already used")
    if record.expires_at <= utc_now():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth session expired")
    record.consumed_at = utc_now()
    db.flush()
    return record


def exchange_authorization_code(provider: str, code: str) -> dict:
    data = {
        "code": code,
        "redirect_uri": oauth_redirect_uri(provider),
        "grant_type": "authorization_code",
    }
    if provider == GOOGLE_DRIVE:
        data.update(
            {
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
            }
        )
        return token_request("https://oauth2.googleapis.com/token", data)

    tenant = settings.microsoft_oauth_tenant or "common"
    data.update(
        {
            "client_id": settings.microsoft_oauth_client_id,
            "client_secret": settings.microsoft_oauth_client_secret,
            "scope": " ".join(MICROSOFT_SCOPES),
        }
    )
    return token_request(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data)


def refresh_access_token(connection: ExternalSourceConnection) -> str:
    refresh_token = decrypt_secret(connection.refresh_token_encrypted)
    if not refresh_token:
        connection.status = "reauth_required"
        connection.error_message = "Refresh token is missing. Reconnect this source."
        raise ExternalProviderError(connection.error_message)

    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    if connection.provider == GOOGLE_DRIVE:
        data.update(
            {
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
            }
        )
        payload = token_request("https://oauth2.googleapis.com/token", data)
    else:
        tenant = settings.microsoft_oauth_tenant or "common"
        data.update(
            {
                "client_id": settings.microsoft_oauth_client_id,
                "client_secret": settings.microsoft_oauth_client_secret,
                "scope": " ".join(MICROSOFT_SCOPES),
            }
        )
        payload = token_request(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data)

    update_connection_tokens(connection, payload)
    connection.status = "connected"
    connection.error_message = ""
    return payload["access_token"]


def get_access_token(connection: ExternalSourceConnection) -> str:
    if connection.expires_at and connection.expires_at > utc_now() + timedelta(minutes=5):
        return decrypt_secret(connection.access_token_encrypted)
    return refresh_access_token(connection)


def token_request(url: str, data: dict[str, str]) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.post(url, data=data)
    if not response.is_success:
        detail = token_error_detail(response)
        raise ExternalProviderError(detail or f"OAuth token request failed with {response.status_code}")
    payload = response.json()
    if not payload.get("access_token"):
        raise ExternalProviderError("OAuth provider did not return an access token")
    return payload


def token_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        return str(payload.get("error_description") or payload.get("error") or "")
    except Exception:
        return response.text[:300]


def fetch_provider_profile(provider: str, access_token: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    if provider == GOOGLE_DRIVE:
        url = "https://openidconnect.googleapis.com/v1/userinfo"
        with httpx.Client(timeout=30) as client:
            response = client.get(url, headers=headers)
        if not response.is_success:
            raise ExternalProviderError("Could not read Google account profile")
        payload = response.json()
        return {
            "email": payload.get("email") or "",
            "name": payload.get("name") or payload.get("email") or "Google Drive",
        }

    with httpx.Client(timeout=30) as client:
        response = client.get("https://graph.microsoft.com/v1.0/me", headers=headers)
    if not response.is_success:
        raise ExternalProviderError("Could not read Microsoft account profile")
    payload = response.json()
    email = payload.get("mail") or payload.get("userPrincipalName") or ""
    return {"email": email, "name": payload.get("displayName") or email or "OneDrive"}


def upsert_connection_from_oauth(
    db: Session,
    *,
    provider: str,
    company_id: UUID,
    user_id: UUID,
    token_payload: dict,
    account_email: str,
    account_name: str,
) -> ExternalSourceConnection:
    account_email = account_email.strip().lower()
    record = db.scalar(
        select(ExternalSourceConnection).where(
            ExternalSourceConnection.company_id == company_id,
            ExternalSourceConnection.provider == provider,
            ExternalSourceConnection.account_email == account_email,
        )
    )
    if record is None:
        record = ExternalSourceConnection(
            company_id=company_id,
            connected_by_user_id=user_id,
            provider=provider,
            account_email=account_email,
            account_name=account_name,
            sync_interval_hours=settings.external_source_sync_interval_hours,
        )
        db.add(record)

    record.connected_by_user_id = user_id
    record.account_name = account_name
    record.status = "connected"
    record.error_message = ""
    update_connection_tokens(record, token_payload)
    db.flush()
    return record


def update_connection_tokens(connection: ExternalSourceConnection, token_payload: dict) -> None:
    connection.access_token_encrypted = encrypt_secret(token_payload.get("access_token") or "")
    refresh_token = token_payload.get("refresh_token")
    if refresh_token:
        connection.refresh_token_encrypted = encrypt_secret(refresh_token)
    connection.token_type = token_payload.get("token_type") or "Bearer"
    scope = token_payload.get("scope") or ""
    connection.scopes = scope.split() if isinstance(scope, str) and scope else connection.scopes
    expires_in = int(token_payload.get("expires_in") or 3600)
    connection.expires_at = utc_now() + timedelta(seconds=max(60, expires_in))


def list_connections_for_company(db: Session, *, company_id: UUID) -> list[ExternalSourceConnection]:
    return list(
        db.scalars(
            select(ExternalSourceConnection)
            .options(selectinload(ExternalSourceConnection.folders), selectinload(ExternalSourceConnection.sync_runs))
            .where(ExternalSourceConnection.company_id == company_id)
            .order_by(ExternalSourceConnection.created_at.desc())
        )
    )


def connection_for_company(
    db: Session,
    *,
    company_id: UUID,
    connection_id: UUID,
) -> ExternalSourceConnection:
    record = db.get(ExternalSourceConnection, connection_id)
    if record is None or record.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="External source connection not found")
    return record


def list_provider_folders(connection: ExternalSourceConnection) -> list[ProviderFolder]:
    access_token = get_access_token(connection)
    folders = provider_client(connection.provider, access_token).list_folders()
    if connection.provider == ONEDRIVE:
        return [ProviderFolder(provider_folder_id="root", name="OneDrive root", path="OneDrive root"), *folders]
    return folders


def replace_selected_folders(
    db: Session,
    *,
    connection: ExternalSourceConnection,
    folders: list[dict],
) -> list[ExternalSourceFolder]:
    existing = list(
        db.scalars(
            select(ExternalSourceFolder).where(ExternalSourceFolder.connection_id == connection.id)
        )
    )
    for folder in existing:
        db.delete(folder)
    db.flush()

    records = []
    for folder in folders:
        record = ExternalSourceFolder(
            company_id=connection.company_id,
            connection_id=connection.id,
            provider_folder_id=folder["provider_folder_id"],
            drive_id=folder.get("drive_id", ""),
            name=folder["name"],
            path=folder.get("path", "") or folder["name"],
            recursive=folder.get("recursive", True),
            sync_enabled=folder.get("sync_enabled", True),
        )
        db.add(record)
        records.append(record)
    db.flush()
    return records


def create_sync_run(
    db: Session,
    *,
    connection: ExternalSourceConnection,
    trigger: str,
) -> tuple[ExternalSourceSyncRun, BackgroundJob]:
    sync_run = ExternalSourceSyncRun(
        company_id=connection.company_id,
        connection_id=connection.id,
        trigger=trigger,
        status=JOB_QUEUED,
    )
    db.add(sync_run)
    db.flush()
    background_job = BackgroundJob(
        company_id=connection.company_id,
        job_type=EXTERNAL_SOURCE_SYNC,
        status=JOB_QUEUED,
        payload={"connection_id": str(connection.id), "sync_run_id": str(sync_run.id)},
        queued_at=utc_now(),
    )
    db.add(background_job)
    db.flush()
    sync_run.current_job_id = background_job.id
    db.flush()
    return sync_run, background_job


def list_sync_runs(db: Session, *, connection: ExternalSourceConnection) -> list[ExternalSourceSyncRun]:
    return list(
        db.scalars(
            select(ExternalSourceSyncRun)
            .where(ExternalSourceSyncRun.connection_id == connection.id)
            .order_by(ExternalSourceSyncRun.created_at.desc())
            .limit(20)
        )
    )


def list_items(db: Session, *, connection: ExternalSourceConnection) -> list[ExternalSourceItem]:
    return list(
        db.scalars(
            select(ExternalSourceItem)
            .where(ExternalSourceItem.connection_id == connection.id)
            .order_by(ExternalSourceItem.updated_at.desc())
        )
    )


def run_external_source_sync(db: Session, *, connection_id: UUID, sync_run_id: UUID) -> ExternalSourceSyncRun:
    connection = db.scalar(
        select(ExternalSourceConnection)
        .options(selectinload(ExternalSourceConnection.folders))
        .where(ExternalSourceConnection.id == connection_id)
    )
    sync_run = db.get(ExternalSourceSyncRun, sync_run_id)
    if connection is None or sync_run is None:
        raise ExternalProviderError("External source sync target not found")

    now = utc_now()
    sync_run.status = JOB_PROCESSING
    sync_run.started_at = now
    sync_run.error_message = ""
    connection.error_message = ""
    db.commit()

    access_token = get_access_token(connection)
    client = provider_client(connection.provider, access_token)
    enabled_folders = [folder for folder in connection.folders if folder.sync_enabled]
    seen_provider_keys: set[tuple[str, str]] = set()

    for folder in enabled_folders:
        provider_folder = ProviderFolder(
            provider_folder_id=folder.provider_folder_id,
            drive_id=folder.drive_id,
            name=folder.name,
            path=folder.path,
        )
        files = client.list_files_for_folder(provider_folder, folder.recursive)
        for provider_file in files:
            sync_run.total_seen += 1
            seen_provider_keys.add((provider_file.drive_id, provider_file.provider_file_id))
            item = upsert_item_from_provider_file(db, connection, folder, provider_file)
            if not is_supported_file(provider_file):
                item.status = "unsupported"
                item.error_message = "Unsupported file type"
                sync_run.total_skipped += 1
                db.commit()
                continue
            if item_is_unchanged(item, provider_file):
                item.status = "synced"
                item.error_message = ""
                item.last_seen_at = now
                sync_run.total_skipped += 1
                db.commit()
                continue
            sync_run.total_queued += 1
            db.commit()
            sync_provider_file(db, connection, item, provider_file, client)
            sync_run.total_synced += 1 if item.status == "synced" else 0
            sync_run.total_failed += 1 if item.status == "failed" else 0
            db.commit()

    mark_deleted_items(db, connection, seen_provider_keys, sync_run)

    now = utc_now()
    sync_run.status = JOB_COMPLETED if sync_run.total_failed == 0 else "completed_with_errors"
    sync_run.completed_at = now
    connection.last_sync_at = now
    connection.next_sync_at = now + timedelta(hours=connection.sync_interval_hours)
    connection.status = "connected" if sync_run.total_failed == 0 else "sync_error"
    connection.error_message = "" if sync_run.total_failed == 0 else "Some files failed to sync"
    db.commit()
    return sync_run


def upsert_item_from_provider_file(
    db: Session,
    connection: ExternalSourceConnection,
    folder: ExternalSourceFolder,
    provider_file: ProviderFile,
) -> ExternalSourceItem:
    item = db.scalar(
        select(ExternalSourceItem).where(
            ExternalSourceItem.connection_id == connection.id,
            ExternalSourceItem.drive_id == provider_file.drive_id,
            ExternalSourceItem.provider_file_id == provider_file.provider_file_id,
        )
    )
    if item is None:
        item = ExternalSourceItem(
            company_id=connection.company_id,
            connection_id=connection.id,
            folder_id=folder.id,
            provider_file_id=provider_file.provider_file_id,
            drive_id=provider_file.drive_id,
            name=provider_file.name,
        )
        db.add(item)

    item.folder_id = folder.id
    item.name = provider_file.name
    item.mime_type = provider_file.mime_type
    item.web_url = provider_file.web_url
    item.size_bytes = provider_file.size_bytes
    item.last_seen_at = utc_now()
    return item


def item_is_unchanged(item: ExternalSourceItem, provider_file: ProviderFile) -> bool:
    if item.status != "synced" or item.knowledge_document_id is None:
        return False
    if provider_file.checksum and item.checksum == provider_file.checksum:
        return True
    if provider_file.etag and item.etag == provider_file.etag:
        return True
    return bool(provider_file.modified_at and item.modified_at == provider_file.modified_at)


def sync_provider_file(
    db: Session,
    connection: ExternalSourceConnection,
    item: ExternalSourceItem,
    provider_file: ProviderFile,
    client,
) -> None:
    item.status = JOB_PROCESSING
    item.error_message = ""
    knowledge_document = ensure_knowledge_document(db, connection, item, provider_file)
    knowledge_document.status = JOB_PROCESSING
    knowledge_document.started_at = utc_now()
    knowledge_document.error_message = ""
    db.commit()

    try:
        content = client.download_file(provider_file)
        if len(content) > settings.upload_max_bytes:
            raise DocumentExtractionError(
                f"File is larger than {settings.upload_max_bytes // (1024 * 1024)} MB"
            )
        with NamedTemporaryFile(suffix=Path(exported_filename(provider_file)).suffix) as temp:
            temp.write(content)
            temp.flush()
            result = extract_document_text(temp.name, exported_filename(provider_file))
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        knowledge_document.status = JOB_FAILED
        knowledge_document.error_message = message[:1000]
        knowledge_document.completed_at = utc_now()
        item.status = "failed"
        item.error_message = message[:1000]
        db.commit()
        return

    if item.knowledge_document_id:
        rag_service.sync_delete_document(external_rag_doc_id(item), connection.company_id)

    knowledge_document.extracted_text = result.text
    knowledge_document.char_count = len(result.text)
    knowledge_document.document_metadata = {
        **result.metadata,
        "external_source_provider": connection.provider,
        "provider_file_id": provider_file.provider_file_id,
        "drive_id": provider_file.drive_id,
        "source_url": provider_file.web_url,
    }
    knowledge_document.status = JOB_INGESTING
    db.commit()
    if result.text.strip():
        rag_service.sync_ingest_document(
            result.text,
            connection.company_id,
            doc_id=external_rag_doc_id(item),
            file_path=provider_file.web_url or provider_file.name,
        )

    now = utc_now()
    knowledge_document.status = JOB_COMPLETED
    knowledge_document.completed_at = now
    knowledge_document.error_message = ""
    item.status = "synced"
    item.checksum = provider_file.checksum
    item.etag = provider_file.etag
    item.modified_at = provider_file.modified_at
    item.last_synced_at = now
    item.error_message = ""
    item.document_metadata = knowledge_document.document_metadata
    db.commit()


def ensure_knowledge_document(
    db: Session,
    connection: ExternalSourceConnection,
    item: ExternalSourceItem,
    provider_file: ProviderFile,
) -> KnowledgeDocument:
    record = db.get(KnowledgeDocument, item.knowledge_document_id) if item.knowledge_document_id else None
    if record is None:
        record = KnowledgeDocument(
            company_id=connection.company_id,
            source_type=connection.provider,
            source_url=provider_file.web_url,
            source_title=provider_file.name,
            status=JOB_QUEUED,
            queued_at=utc_now(),
        )
        db.add(record)
        db.flush()
        item.knowledge_document_id = record.id
    record.source_type = connection.provider
    record.source_url = provider_file.web_url
    record.source_title = provider_file.name
    return record


def mark_deleted_items(
    db: Session,
    connection: ExternalSourceConnection,
    seen_provider_keys: set[tuple[str, str]],
    sync_run: ExternalSourceSyncRun,
) -> None:
    records = db.scalars(
        select(ExternalSourceItem).where(
            ExternalSourceItem.connection_id == connection.id,
            ExternalSourceItem.status != "deleted",
        )
    ).all()
    for item in records:
        if (item.drive_id, item.provider_file_id) in seen_provider_keys:
            continue
        if item.knowledge_document_id:
            rag_service.sync_delete_document(external_rag_doc_id(item), connection.company_id)
            knowledge_document = db.get(KnowledgeDocument, item.knowledge_document_id)
            if knowledge_document is not None:
                db.delete(knowledge_document)
            item.knowledge_document_id = None
        item.status = "deleted"
        item.error_message = ""
        sync_run.total_deleted += 1


def fail_sync_run(
    db: Session,
    *,
    sync_run: ExternalSourceSyncRun,
    connection: ExternalSourceConnection | None,
    message: str,
) -> None:
    now = utc_now()
    sync_run.status = JOB_FAILED
    sync_run.error_message = message
    sync_run.completed_at = now
    if connection is not None:
        connection.status = "sync_error" if connection.status != "reauth_required" else connection.status
        connection.error_message = message
    db.flush()


def due_connections(db: Session) -> list[ExternalSourceConnection]:
    candidates = list(
        db.scalars(
            select(ExternalSourceConnection).where(
                ExternalSourceConnection.status.in_(["connected", "sync_error"]),
                ExternalSourceConnection.next_sync_at.is_not(None),
                ExternalSourceConnection.next_sync_at <= utc_now(),
            )
        )
    )
    due = []
    for connection in candidates:
        active_run = db.scalar(
            select(ExternalSourceSyncRun).where(
                ExternalSourceSyncRun.connection_id == connection.id,
                ExternalSourceSyncRun.status.in_([JOB_QUEUED, JOB_PROCESSING]),
            )
        )
        if active_run is None:
            due.append(connection)
    return due


def external_rag_doc_id(item: ExternalSourceItem) -> str:
    return f"external:{item.connection_id}:{item.drive_id}:{item.provider_file_id}"


def provider_label(provider: str) -> str:
    return "Google Drive" if provider == GOOGLE_DRIVE else "OneDrive"


def oauth_redirect_uri(provider: str) -> str:
    base = settings.backend_public_url.rstrip("/")
    return f"{base}{settings.api_v1_prefix}/external-sources/oauth/{provider}/callback"


def ensure_provider_configured(provider: str) -> None:
    if provider == GOOGLE_DRIVE:
        if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
            raise HTTPException(status_code=400, detail="Google Drive OAuth is not configured")
        return
    if not settings.microsoft_oauth_client_id or not settings.microsoft_oauth_client_secret:
        raise HTTPException(status_code=400, detail="OneDrive OAuth is not configured")


def hash_state(state: str) -> str:
    return sha256(state.encode("utf-8")).hexdigest()


def safe_redirect_path(path: str) -> str:
    if not path.startswith("/") or path.startswith("//"):
        return MANAGE_REDIRECT_PATH
    return path[:500]


def frontend_redirect(path: str, params: dict[str, str]) -> str:
    separator = "&" if "?" in path else "?"
    return f"{settings.frontend_base_url.rstrip('/')}{path}{separator}{urlencode(params)}"
