"""Admin endpoints for managing Chatwoot connections (US-03 backend).

These rows are how the bot worker discovers which tenant owns an incoming
Chatwoot webhook (via account_id + inbox_id lookup). Without a connection
row, the worker falls back to env-var-based dev mode — fine for solo dev
but blocks real multi-tenant testing.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import MessageResponse
from app.schemas.chatwoot import (
    ChatwootConnectionCreate,
    ChatwootConnectionPublic,
    ChatwootConnectionUpdate,
)
from app.services.auth import audit_event
from app.services.chatwoot_connections import (
    connection_public_dict,
    create_connection,
    delete_connection,
    get_connection_for_company,
    list_connections,
    update_connection,
)
from app.services.settings import current_company, require_company_admin

router = APIRouter(prefix="/chatwoot", tags=["chatwoot"])


@router.get("/connections", response_model=list[ChatwootConnectionPublic])
def list_chatwoot_connections(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChatwootConnectionPublic]:
    company = current_company(db, current_user, company_id)
    return [
        ChatwootConnectionPublic.model_validate(connection_public_dict(record))
        for record in list_connections(db, company)
    ]


@router.post(
    "/connections", response_model=ChatwootConnectionPublic, status_code=status.HTTP_201_CREATED
)
def create_chatwoot_connection(
    payload: ChatwootConnectionCreate,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatwootConnectionPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = create_connection(
        db,
        company=company,
        chatwoot_base_url=str(payload.chatwoot_base_url),
        chatwoot_account_id=payload.chatwoot_account_id,
        chatwoot_inbox_id=payload.chatwoot_inbox_id,
        chatwoot_agent_bot_id=payload.chatwoot_agent_bot_id,
        chatwoot_agent_bot_token=payload.chatwoot_agent_bot_token,
        webhook_secret=payload.webhook_secret,
    )
    audit_event(
        db,
        event_type="chatwoot_connection_created",
        request=request,
        user_id=current_user.id,
        metadata={
            "connection_id": str(record.id),
            "chatwoot_account_id": record.chatwoot_account_id,
            "chatwoot_inbox_id": record.chatwoot_inbox_id,
        },
    )
    db.commit()
    db.refresh(record)
    return ChatwootConnectionPublic.model_validate(connection_public_dict(record))


@router.get("/connections/{connection_id}", response_model=ChatwootConnectionPublic)
def get_chatwoot_connection(
    connection_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatwootConnectionPublic:
    company = current_company(db, current_user, company_id)
    record = get_connection_for_company(db, company, connection_id)
    return ChatwootConnectionPublic.model_validate(connection_public_dict(record))


@router.patch("/connections/{connection_id}", response_model=ChatwootConnectionPublic)
def update_chatwoot_connection(
    connection_id: UUID,
    payload: ChatwootConnectionUpdate,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatwootConnectionPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = get_connection_for_company(db, company, connection_id)
    record = update_connection(
        db,
        record=record,
        company=company,
        chatwoot_base_url=str(payload.chatwoot_base_url) if payload.chatwoot_base_url else None,
        chatwoot_account_id=payload.chatwoot_account_id,
        chatwoot_inbox_id=payload.chatwoot_inbox_id,
        chatwoot_agent_bot_id=payload.chatwoot_agent_bot_id,
        chatwoot_agent_bot_token=payload.chatwoot_agent_bot_token,
        webhook_secret=payload.webhook_secret,
        status_value=payload.status,
    )
    audit_event(
        db,
        event_type="chatwoot_connection_updated",
        request=request,
        user_id=current_user.id,
        metadata={"connection_id": str(record.id)},
    )
    db.commit()
    db.refresh(record)
    return ChatwootConnectionPublic.model_validate(connection_public_dict(record))


@router.delete("/connections/{connection_id}", response_model=MessageResponse)
def delete_chatwoot_connection(
    connection_id: UUID,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = get_connection_for_company(db, company, connection_id)
    delete_connection(db, record)
    audit_event(
        db,
        event_type="chatwoot_connection_deleted",
        request=request,
        user_id=current_user.id,
        metadata={"connection_id": str(connection_id)},
    )
    db.commit()
    return MessageResponse(message="Chatwoot connection removed")
