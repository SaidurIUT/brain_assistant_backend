import json
import logging
from enum import Enum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chatwoot import ChatwootConnection, ChatwootEvent
from app.services import event_normalizer, signature_verifier

logger = logging.getLogger(__name__)


class IngestResult(str, Enum):
    OK = "ok"
    DUPLICATE = "duplicate"
    INVALID_SIGNATURE = "invalid_signature"


def ingest(
    *,
    db: Session,
    delivery_id: str,
    raw_body: bytes,
    timestamp: str,
    signature: str,
) -> IngestResult:
    """
    Full ingestion pipeline for one Chatwoot AgentBot webhook delivery.

    Steps:
      1. Resolve the webhook secret (DB connection row → ENV fallback)
      2. Verify HMAC signature — return INVALID_SIGNATURE if bad
      3. Check delivery_id uniqueness — return DUPLICATE if seen before
      4. Parse + normalise payload
      5. Persist ChatwootEvent (status=received)
      6. Enqueue background processing job
      7. Return OK

    Always returns OK (not INVALID_SIGNATURE) on steps 3-6 errors so Chatwoot
    does not retry — we handle retries from the failed status ourselves.
    """
    secret = _resolve_secret(db)

    if not signature_verifier.verify(
        raw_body=raw_body,
        timestamp=timestamp,
        signature=signature,
        secret=secret,
    ):
        logger.warning("Invalid webhook signature for delivery=%s", delivery_id)
        return IngestResult.INVALID_SIGNATURE

    existing = db.scalar(select(ChatwootEvent.id).where(ChatwootEvent.delivery_id == delivery_id))
    if existing is not None:
        logger.info("Duplicate delivery ignored: %s", delivery_id)
        return IngestResult.DUPLICATE

    try:
        payload = json.loads(raw_body)
        event_name = payload.get("event", "unknown")
        normalized = event_normalizer.normalize(payload, event_name)

        event = ChatwootEvent(
            delivery_id=delivery_id,
            event_name=event_name,
            payload_json=payload,
            signature_valid=True,
            status="received",
            **normalized,
        )
        db.add(event)
        db.flush()
        db.commit()
        db.refresh(event)

        _enqueue_processing(str(event.id))

    except IntegrityError:
        db.rollback()
        logger.info("Duplicate delivery (race condition) ignored: %s", delivery_id)
        return IngestResult.DUPLICATE

    except Exception as exc:
        db.rollback()
        logger.exception("Failed to process webhook delivery=%s", delivery_id)
        _persist_failed_event(db, delivery_id, raw_body, exc)

    return IngestResult.OK


def _resolve_secret(db: Session) -> str:
    conn = db.scalar(
        select(ChatwootConnection).where(ChatwootConnection.status == "active").limit(1)
    )
    if conn and conn.webhook_secret:
        return conn.webhook_secret
    return settings.chatwoot_webhook_secret


def _enqueue_processing(event_id: str) -> None:
    try:
        from app.workers.process_event import process_chatwoot_event
        process_chatwoot_event.delay(event_id)
    except Exception:
        logger.warning("Could not enqueue event %s — broker unavailable", event_id)


def _persist_failed_event(db: Session, delivery_id: str, raw_body: bytes, exc: Exception) -> None:
    try:
        payload = json.loads(raw_body)
    except Exception:
        payload = {"_raw": raw_body.decode("utf-8", errors="replace")}

    event = ChatwootEvent(
        delivery_id=delivery_id,
        event_name=payload.get("event", "unknown"),
        payload_json=payload,
        signature_valid=True,
        status="failed",
        error_message=str(exc),
    )
    db.add(event)
    db.commit()
