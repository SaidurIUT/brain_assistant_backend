"""Service layer for managing chatwoot_connections rows."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company
from app.models.chatwoot import ChatwootConnection


def _mask_token(token: str | None) -> str:
    """Show only last 4 characters of a token; never the full value.

    The full token is in postgres for the worker to use; this masked form
    is what we return in API responses and log lines so a screenshot can't
    leak the credential.
    """
    if not token:
        return ""
    if len(token) <= 4:
        return "*" * len(token)
    return f"****{token[-4:]}"


def connection_public_dict(record: ChatwootConnection) -> dict:
    """Render a ChatwootConnection for API response: tokens masked, secret
    presence-only.
    """
    return {
        "id": record.id,
        "company_id": record.company_id,
        "chatwoot_base_url": record.chatwoot_base_url,
        "chatwoot_account_id": record.chatwoot_account_id,
        "chatwoot_inbox_id": record.chatwoot_inbox_id,
        "chatwoot_agent_bot_id": record.chatwoot_agent_bot_id,
        "chatwoot_agent_bot_token_masked": _mask_token(record.chatwoot_agent_bot_token),
        "webhook_secret_set": bool(record.webhook_secret),
        "status": record.status,
        "last_health_check_at": record.last_health_check_at,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def list_connections(db: Session, company: Company) -> list[ChatwootConnection]:
    return list(
        db.scalars(
            select(ChatwootConnection)
            .where(ChatwootConnection.company_id == company.id)
            .order_by(ChatwootConnection.created_at.desc())
        )
    )


def get_connection_for_company(
    db: Session, company: Company, connection_id: UUID
) -> ChatwootConnection:
    record = db.get(ChatwootConnection, connection_id)
    if record is None or record.company_id != company.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chatwoot connection not found"
        )
    return record


def _find_duplicate(
    db: Session,
    *,
    company: Company,
    chatwoot_account_id: int,
    chatwoot_inbox_id: int,
    exclude_id: UUID | None = None,
) -> ChatwootConnection | None:
    """A given (account, inbox) pair can only have one active connection per
    company. Service-level uniqueness check; no DB constraint required.
    """
    query = select(ChatwootConnection).where(
        ChatwootConnection.company_id == company.id,
        ChatwootConnection.chatwoot_account_id == chatwoot_account_id,
        ChatwootConnection.chatwoot_inbox_id == chatwoot_inbox_id,
    )
    if exclude_id is not None:
        query = query.where(ChatwootConnection.id != exclude_id)
    return db.scalar(query)


def create_connection(
    db: Session,
    *,
    company: Company,
    chatwoot_base_url: str,
    chatwoot_account_id: int,
    chatwoot_inbox_id: int,
    chatwoot_agent_bot_id: int,
    chatwoot_agent_bot_token: str,
    webhook_secret: str | None,
) -> ChatwootConnection:
    if _find_duplicate(
        db,
        company=company,
        chatwoot_account_id=chatwoot_account_id,
        chatwoot_inbox_id=chatwoot_inbox_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A connection already exists for this Chatwoot account+inbox pair "
                "in this workspace. Update or delete the existing connection first."
            ),
        )
    record = ChatwootConnection(
        company_id=company.id,
        chatwoot_base_url=chatwoot_base_url.rstrip("/"),
        chatwoot_account_id=chatwoot_account_id,
        chatwoot_inbox_id=chatwoot_inbox_id,
        chatwoot_agent_bot_id=chatwoot_agent_bot_id,
        chatwoot_agent_bot_token=chatwoot_agent_bot_token,
        webhook_secret=webhook_secret,
        status="active",
    )
    db.add(record)
    db.flush()
    return record


def update_connection(
    db: Session,
    *,
    record: ChatwootConnection,
    company: Company,
    chatwoot_base_url: str | None,
    chatwoot_account_id: int | None,
    chatwoot_inbox_id: int | None,
    chatwoot_agent_bot_id: int | None,
    chatwoot_agent_bot_token: str | None,
    webhook_secret: str | None,
    status_value: str | None,
) -> ChatwootConnection:
    new_account = chatwoot_account_id if chatwoot_account_id is not None else record.chatwoot_account_id
    new_inbox = chatwoot_inbox_id if chatwoot_inbox_id is not None else record.chatwoot_inbox_id
    if new_account != record.chatwoot_account_id or new_inbox != record.chatwoot_inbox_id:
        if _find_duplicate(
            db,
            company=company,
            chatwoot_account_id=new_account,
            chatwoot_inbox_id=new_inbox,
            exclude_id=record.id,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Another connection already covers this Chatwoot account+inbox "
                    "pair for this workspace."
                ),
            )

    if chatwoot_base_url is not None:
        record.chatwoot_base_url = chatwoot_base_url.rstrip("/")
    if chatwoot_account_id is not None:
        record.chatwoot_account_id = chatwoot_account_id
    if chatwoot_inbox_id is not None:
        record.chatwoot_inbox_id = chatwoot_inbox_id
    if chatwoot_agent_bot_id is not None:
        record.chatwoot_agent_bot_id = chatwoot_agent_bot_id
    if chatwoot_agent_bot_token is not None:
        record.chatwoot_agent_bot_token = chatwoot_agent_bot_token
    if webhook_secret is not None:
        record.webhook_secret = webhook_secret
    if status_value is not None:
        record.status = status_value

    db.flush()
    return record


def delete_connection(db: Session, record: ChatwootConnection) -> None:
    db.delete(record)
    db.flush()
