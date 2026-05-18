"""Service layer for per-tenant system prompts (US-14 T1+T2).

The bot worker resolves a tenant's prompt via `resolve_prompt_content` —
returns the custom prompt if set, otherwise the built-in default.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanySystemPrompt, User

# Built-in default. Lifted out of process_event so the API can serve it on
# GET when a tenant has no custom prompt set yet.
DEFAULT_SYSTEM_PROMPT = """\
You are a customer support assistant. Reply directly to the customer using ONLY
the provided context.

Formatting rules:
- Lead with the answer in the first 1-2 sentences.
- Keep paragraphs short (2-3 sentences).
- Use bullet points when listing items, steps, or options.
- Do not include section headers like "### Answer", "### References", or
  "### Content & Grounding".
- Do not list source document names at the end.
- Do not say "based on the context" or "according to the documents" — answer
  naturally as if you are the company speaking to the customer.
- If the context doesn't cover the question, say so in one short sentence
  without apologizing repeatedly.

Tone: warm, concise, professional. Match the level of formality the customer
is using. Avoid filler phrases."""


def get_prompt_for_company(db: Session, company: Company) -> CompanySystemPrompt | None:
    """Return the tenant's row if set, else None."""
    return db.scalar(
        select(CompanySystemPrompt).where(CompanySystemPrompt.company_id == company.id)
    )


def upsert_prompt_for_company(
    db: Session,
    *,
    company: Company,
    user: User,
    content: str,
) -> CompanySystemPrompt:
    record = get_prompt_for_company(db, company)
    if record is None:
        record = CompanySystemPrompt(
            company_id=company.id,
            content=content,
            updated_by_user_id=user.id,
        )
        db.add(record)
    else:
        record.content = content
        record.updated_by_user_id = user.id
    db.flush()
    return record


def delete_prompt_for_company(db: Session, company: Company) -> bool:
    record = get_prompt_for_company(db, company)
    if record is None:
        return False
    db.delete(record)
    db.flush()
    return True


def resolve_prompt_content(db: Session, company: Company) -> str:
    """Used by the bot worker — never raises, always returns a usable prompt.

    Falls back to the default if the tenant has no custom prompt OR the DB
    read fails for any reason. The bot must always have *some* prompt to
    send to the LLM; this is the chokepoint that guarantees that.
    """
    try:
        record = get_prompt_for_company(db, company)
        if record and record.content.strip():
            return record.content
    except Exception:
        pass
    return DEFAULT_SYSTEM_PROMPT


def resolve_prompt_content_by_company_id(db: Session, company_id) -> str:
    """Worker-friendly variant — avoids loading a Company ORM object just to
    fetch the prompt. Returns the default if the tenant has no custom prompt
    OR the DB read fails for any reason.
    """
    try:
        record = db.scalar(
            select(CompanySystemPrompt).where(CompanySystemPrompt.company_id == company_id)
        )
        if record and record.content.strip():
            return record.content
    except Exception:
        pass
    return DEFAULT_SYSTEM_PROMPT


def prompt_public_dict(record: CompanySystemPrompt | None, company: Company) -> dict:
    """Render the GET response, including the is_default flag when the tenant
    is being served the built-in fallback (no DB row).
    """
    if record is None:
        return {
            "id": None,
            "company_id": company.id,
            "content": DEFAULT_SYSTEM_PROMPT,
            "is_default": True,
            "updated_by_user_id": None,
            "created_at": None,
            "updated_at": None,
        }
    return {
        "id": record.id,
        "company_id": record.company_id,
        "content": record.content,
        "is_default": False,
        "updated_by_user_id": record.updated_by_user_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
