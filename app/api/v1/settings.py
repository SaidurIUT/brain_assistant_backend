from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.auth import MessageResponse, UserPublic, UserUpdateRequest
from app.schemas.settings import (
    BrandPublic,
    BrandUpdateRequest,
    CompanyPublic,
    CompanyUpdateRequest,
    MemberCreateRequest,
    MemberPublic,
    MemberRoleUpdateRequest,
    SettingsPublic,
    WorkspaceSummaryPublic,
)
from app.services.auth import audit_event, create_invitation_for_member
from app.services.settings import (
    active_workspace_memberships,
    create_member,
    current_company,
    ensure_brand_settings,
    member_for_company,
    require_company_admin,
    update_brand,
    update_company,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsPublic)
def get_settings(
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SettingsPublic:
    company = current_company(db, current_user, company_id)
    brand = ensure_brand_settings(db, company)
    db.commit()
    db.refresh(company)
    memberships = active_workspace_memberships(db, current_user)
    current_member = next((member for member in memberships if member.company_id == company.id), None)
    return SettingsPublic(
        user=UserPublic.model_validate(current_user),
        company=CompanyPublic.model_validate(company),
        brand=BrandPublic.model_validate(brand),
        members=[MemberPublic.model_validate(member) for member in company.members],
        workspaces=[
            WorkspaceSummaryPublic(
                id=member.company.id,
                name=member.company.name,
                role=member.role,
                status=member.status,
            )
            for member in memberships
        ],
        current_role=current_member.role if current_member else "administrator",
    )


@router.patch("/user", response_model=UserPublic)
def update_user_profile(
    payload: UserUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserPublic:
    current_user.first_name = payload.first_name
    current_user.last_name = payload.last_name
    audit_event(db, event_type="user_profile_updated", request=request, user_id=current_user.id)
    db.commit()
    db.refresh(current_user)
    return UserPublic.model_validate(current_user)


@router.patch("/company", response_model=CompanyPublic)
def update_company_profile(
    payload: CompanyUpdateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanyPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    update_company(company, payload)
    audit_event(db, event_type="company_updated", request=request, user_id=current_user.id)
    db.commit()
    db.refresh(company)
    return CompanyPublic.model_validate(company)


@router.patch("/brand", response_model=BrandPublic)
def update_brand_settings(
    payload: BrandUpdateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BrandPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    brand = update_brand(ensure_brand_settings(db, company), payload)
    audit_event(db, event_type="brand_updated", request=request, user_id=current_user.id)
    db.commit()
    db.refresh(brand)
    return BrandPublic.model_validate(brand)


@router.post("/members", response_model=MemberPublic, status_code=201)
def add_member(
    payload: MemberCreateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemberPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    if current_user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Verify your email before inviting workspace members")
    member = create_member(db, company, current_user, payload)
    create_invitation_for_member(db, member)
    audit_event(db, event_type="member_added", request=request, user_id=current_user.id, metadata={"role": member.role})
    db.commit()
    db.refresh(member)
    return MemberPublic.model_validate(member)


@router.patch("/members/{member_id}/role", response_model=MemberPublic)
def update_member_role(
    member_id: UUID,
    payload: MemberRoleUpdateRequest,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemberPublic:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    member = member_for_company(db, company, member_id)
    member.role = payload.role
    audit_event(db, event_type="member_role_updated", request=request, user_id=current_user.id, metadata={"role": member.role})
    db.commit()
    db.refresh(member)
    return MemberPublic.model_validate(member)


@router.delete("/members/{member_id}", response_model=MessageResponse)
def remove_member(
    member_id: UUID,
    request: Request,
    company_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    company = current_company(db, current_user, company_id)
    require_company_admin(db, current_user, company)
    member = member_for_company(db, company, member_id)
    db.delete(member)
    audit_event(db, event_type="member_removed", request=request, user_id=current_user.id)
    db.commit()
    return MessageResponse(message="Member removed")
