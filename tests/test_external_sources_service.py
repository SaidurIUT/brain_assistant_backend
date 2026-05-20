from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.api.v1.external_sources import item_public
from app.services import external_sources
from app.services.external_provider_clients import ProviderFile


def test_google_oauth_url_requests_offline_drive_access(monkeypatch) -> None:
    monkeypatch.setattr(external_sources.settings, "google_oauth_client_id", "google-client")
    monkeypatch.setattr(external_sources.settings, "backend_public_url", "http://api.test")
    monkeypatch.setattr(external_sources.settings, "api_v1_prefix", "/api/v1")

    url = external_sources.oauth_authorization_url("google_drive", "state-123")

    assert "client_id=google-client" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "drive.readonly" in url
    assert "state=state-123" in url


def test_onedrive_oauth_url_requests_offline_files_access(monkeypatch) -> None:
    monkeypatch.setattr(external_sources.settings, "microsoft_oauth_client_id", "ms-client")
    monkeypatch.setattr(external_sources.settings, "microsoft_oauth_tenant", "common")
    monkeypatch.setattr(external_sources.settings, "backend_public_url", "http://api.test")
    monkeypatch.setattr(external_sources.settings, "api_v1_prefix", "/api/v1")

    url = external_sources.oauth_authorization_url("onedrive", "state-123")

    assert "client_id=ms-client" in url
    assert "offline_access" in url
    assert "Files.Read" in url
    assert "state=state-123" in url


def test_token_update_encrypts_access_and_refresh_tokens() -> None:
    connection = SimpleNamespace(
        access_token_encrypted="",
        refresh_token_encrypted="",
        token_type="",
        scopes=[],
        expires_at=None,
    )

    external_sources.update_connection_tokens(
        connection,
        {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "token_type": "Bearer",
            "scope": "Files.Read offline_access",
            "expires_in": 3600,
        },
    )

    assert "access-secret" not in connection.access_token_encrypted
    assert "refresh-secret" not in connection.refresh_token_encrypted
    assert connection.scopes == ["Files.Read", "offline_access"]
    assert connection.expires_at is not None


def test_item_is_unchanged_by_checksum() -> None:
    item = SimpleNamespace(status="synced", knowledge_document_id=uuid4(), checksum="abc", etag="", modified_at=None)
    provider_file = ProviderFile(
        provider_file_id="file-1",
        name="policy.pdf",
        mime_type="application/pdf",
        web_url="",
        modified_at=None,
        size_bytes=100,
        checksum="abc",
    )

    assert external_sources.item_is_unchanged(item, provider_file)


def test_item_is_changed_when_not_synced() -> None:
    item = SimpleNamespace(status="failed", knowledge_document_id=uuid4(), checksum="abc", etag="", modified_at=None)
    provider_file = ProviderFile(
        provider_file_id="file-1",
        name="policy.pdf",
        mime_type="application/pdf",
        web_url="",
        modified_at=None,
        size_bytes=100,
        checksum="abc",
    )

    assert not external_sources.item_is_unchanged(item, provider_file)


def test_external_rag_doc_id_is_stable() -> None:
    connection_id = uuid4()
    item = SimpleNamespace(connection_id=connection_id, drive_id="drive", provider_file_id="file")

    assert external_sources.external_rag_doc_id(item) == f"external:{connection_id}:drive:file"


def test_item_public_includes_extraction_metadata() -> None:
    now = datetime.now(UTC)
    knowledge_document_id = uuid4()
    item = SimpleNamespace(
        id=uuid4(),
        connection_id=uuid4(),
        knowledge_document_id=knowledge_document_id,
        provider_file_id="file",
        drive_id="drive",
        name="runbook.md",
        mime_type="text/markdown",
        web_url="https://drive.example/runbook",
        checksum="",
        etag="etag",
        modified_at=None,
        size_bytes=512,
        status="synced",
        last_synced_at=now,
        last_seen_at=now,
        error_message="",
        created_at=now,
        updated_at=now,
        knowledge_document=SimpleNamespace(status="completed", char_count=42, error_message=""),
    )

    public = item_public(item)

    assert public.knowledge_document_id == knowledge_document_id
    assert public.extraction_status == "completed"
    assert public.extracted_char_count == 42
    assert public.extraction_error == ""
