"""Admin API for per-tenant system prompts (US-14 T2).

GET    /api/v1/system-prompt      — fetch active prompt (returns the built-in
                                    default + is_default=True if not customised)
PUT    /api/v1/system-prompt      — upsert the tenant's custom prompt (admin)
DELETE /api/v1/system-prompt      — drop custom; tenant returns to default
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import MessageResponse
from app.schemas.system_prompts import SystemPromptPublic, SystemPromptRevisionPublic, SystemPromptRollbackRequest, SystemPromptUpsertRequest
from app.services.auth import audit_event
from app.services.settings import current_company, require_company_admin
from app.services.system_prompts import (
    delete_prompt_for_company,
    get_prompt_for_company,
    list_revisions_for_company,
    prompt_public_dict,
    rollback_to_revision,
    upsert_prompt_for_company,
)

router = APIRouter(prefix="/system-prompt", tags=["system-prompt"])


@router.get("", response_model=SystemPromptPublic)
def read_system_prompt(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SystemPromptPublic:
    company = current_company(db, current_user, company_id)
    record = get_prompt_for_company(db, company)
    return SystemPromptPublic.model_validate(prompt_public_dict(record, company))


@router.put("", response_model=SystemPromptPublic)
def upsert_system_prompt(
    payload: SystemPromptUpsertRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SystemPromptPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = upsert_prompt_for_company(
        db, company=company, user=current_user, content=payload.content
    )
    audit_event(
        db,
        event_type="system_prompt_updated",
        request=request,
        user_id=current_user.id,
        metadata={"company_id": str(company.id), "length": len(payload.content)},
    )
    db.commit()
    db.refresh(record)
    return SystemPromptPublic.model_validate(prompt_public_dict(record, company))


@router.post("/rollback", response_model=SystemPromptPublic)
def rollback_system_prompt(
    payload: SystemPromptRollbackRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SystemPromptPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    record = rollback_to_revision(db, company=company, user=current_user, revision_id=payload.revision_id)
    audit_event(
        db,
        event_type="system_prompt_rolled_back",
        request=request,
        user_id=current_user.id,
        metadata={"company_id": str(company.id), "revision_id": str(payload.revision_id)},
    )
    db.commit()
    db.refresh(record)
    return SystemPromptPublic.model_validate(prompt_public_dict(record, company))


@router.get("/history", response_model=list[SystemPromptRevisionPublic])
def read_system_prompt_history(
    company_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SystemPromptRevisionPublic]:
    company = current_company(db, current_user, company_id)
    return [
        SystemPromptRevisionPublic.model_validate(r)
        for r in list_revisions_for_company(db, company, limit=limit)
    ]


@router.delete("", response_model=MessageResponse)
def reset_system_prompt(
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    deleted = delete_prompt_for_company(db, company)
    if deleted:
        audit_event(
            db,
            event_type="system_prompt_reset_to_default",
            request=request,
            user_id=current_user.id,
            metadata={"company_id": str(company.id)},
        )
    db.commit()
    return MessageResponse(
        message="Custom system prompt removed" if deleted else "No custom prompt was set"
    )
