from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BrandSettings, Company, CompanyMember, User
from app.schemas.settings import BrandUpdateRequest, CompanyUpdateRequest, MemberCreateRequest

ADMIN_ROLES = {"administrator", "manager"}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_default_workspace(db: Session, user: User) -> Company:
    company = Company(created_by_user_id=user.id)
    db.add(company)
    db.flush()
    db.add(
        BrandSettings(
            company_id=company.id,
            workspace_name="Brain Assistant Workspace",
            assistant_name="Brain Assistant",
        )
    )
    db.add(
        CompanyMember(
            company_id=company.id,
            user_id=user.id,
            email=user.email,
            email_normalized=user.email_normalized,
            first_name=user.first_name,
            last_name=user.last_name,
            role="administrator",
            status="active",
            invited_by_user_id=user.id,
        )
    )
    return company


def current_company(db: Session, user: User, company_id: UUID | None = None) -> Company:
    query = select(CompanyMember).where(CompanyMember.user_id == user.id, CompanyMember.status == "active")
    if company_id is not None:
        query = query.where(CompanyMember.company_id == company_id)
    member = db.scalar(query.order_by(CompanyMember.created_at.asc()))
    if member is None:
        if company_id is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
        company = create_default_workspace(db, user)
        db.commit()
        db.refresh(company)
        return company
    return member.company


def active_workspace_memberships(db: Session, user: User) -> list[CompanyMember]:
    return list(
        db.scalars(
            select(CompanyMember)
            .where(CompanyMember.user_id == user.id, CompanyMember.status == "active")
            .order_by(CompanyMember.created_at.asc())
        )
    )


def require_company_admin(db: Session, user: User, company: Company) -> CompanyMember:
    member = db.scalar(
        select(CompanyMember).where(
            CompanyMember.company_id == company.id,
            CompanyMember.user_id == user.id,
            CompanyMember.status == "active",
        )
    )
    if member is None or member.role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage this workspace",
        )
    return member


def ensure_brand_settings(db: Session, company: Company) -> BrandSettings:
    if company.brand_settings is None:
        company.brand_settings = BrandSettings(company_id=company.id)
        db.flush()
    return company.brand_settings


def update_company(company: Company, payload: CompanyUpdateRequest) -> Company:
    company.name = payload.name
    company.industry = payload.industry
    company.team_size = payload.team_size
    company.description = payload.description
    company.primary_language = payload.primary_language
    return company


def update_brand(brand: BrandSettings, payload: BrandUpdateRequest) -> BrandSettings:
    brand.workspace_name = payload.workspace_name
    brand.assistant_name = payload.assistant_name
    brand.widget_greeting = payload.widget_greeting
    brand.primary_color = payload.primary_color
    brand.accent_color = payload.accent_color
    brand.widget_background = payload.widget_background
    brand.logo_url = payload.logo_url
    return brand


def create_member(db: Session, company: Company, inviter: User, payload: MemberCreateRequest) -> CompanyMember:
    email_normalized = normalize_email(str(payload.email))
    existing_user = db.scalar(select(User).where(User.email_normalized == email_normalized))
    member = CompanyMember(
        company_id=company.id,
        user_id=existing_user.id if existing_user else None,
        email=str(payload.email),
        email_normalized=email_normalized,
        first_name=payload.first_name,
        last_name=payload.last_name,
        role=payload.role,
        status="invited",
        invited_by_user_id=inviter.id,
    )
    db.add(member)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This member is already in the workspace",
        ) from exc
    return member


def member_for_company(db: Session, company: Company, member_id: UUID) -> CompanyMember:
    member = db.get(CompanyMember, member_id)
    if member is None or member.company_id != company.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return member
