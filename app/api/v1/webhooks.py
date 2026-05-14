import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.webhook_ingestion import IngestResult, ingest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/chatwoot/agent-bot")
async def agent_bot_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """
    Receives Chatwoot AgentBot webhook events.

    Chatwoot posts here for every message_created, conversation_status_changed,
    and related events on inboxes that have an AgentBot attached.

    Must respond within 5 seconds or Chatwoot retries (up to 3 times, 3s apart).
    All AI processing is deferred to the Celery worker — this endpoint only
    stores the event and returns 200.
    """
    raw_body = await request.body()

    result = ingest(
        db=db,
        delivery_id=request.headers.get("x-chatwoot-delivery", ""),
        raw_body=raw_body,
        timestamp=request.headers.get("x-chatwoot-timestamp", ""),
        signature=request.headers.get("x-chatwoot-signature", ""),
    )

    if result == IngestResult.INVALID_SIGNATURE:
        return Response(content="Invalid signature", status_code=401)

    return Response(status_code=200)
