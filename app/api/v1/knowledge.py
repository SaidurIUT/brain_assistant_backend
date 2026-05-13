from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.auth import User
from app.services import rag_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class IngestRequest(BaseModel):
    content: str


@router.post("/ingest", status_code=202)
async def ingest_document(
    payload: IngestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Ingest a text document into the LightRAG knowledge base."""
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    await rag_service.ingest(payload.content)
    return {"message": "Document ingested successfully"}
