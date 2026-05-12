import logging
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.datetime import utc_now
from app.db.session import get_worker_db
from app.models.chatwoot import ChatwootConnection, ChatwootEvent
from app.workers.celery_app import celery

logger = logging.getLogger(__name__)

_HARDCODED_REPLY = "Thanks for your message. I will help you shortly."


@celery.task(bind=True, max_retries=3, default_retry_delay=30)
def process_chatwoot_event(self, event_id: str) -> None:
    """
    Process a stored ChatwootEvent after ingestion.

    For incoming customer messages:
      - Resolve the active Chatwoot connection for this account + inbox
      - Post a reply back to Chatwoot via the AgentBot API
      - Mark the event processed

    Outgoing messages (bot replies firing back as webhooks) are skipped to
    prevent infinite loops. US6 will add confidence/handoff logic here.
    """
    with get_worker_db() as db:
        event = db.scalar(select(ChatwootEvent).where(ChatwootEvent.id == UUID(event_id)))

        if event is None:
            logger.warning("process_chatwoot_event: event %s not found", event_id)
            return

        if event.status != "received":
            logger.info("process_chatwoot_event: event %s already %s, skipping", event_id, event.status)
            return

        if not event.is_incoming_message:
            event.status = "processed"
            event.processed_at = utc_now()
            return

        connection = _resolve_connection(db, event.account_id, event.inbox_id)
        if connection is None:
            logger.error(
                "process_chatwoot_event: no active connection for account=%s inbox=%s",
                event.account_id,
                event.inbox_id,
            )
            event.status = "failed"
            event.error_message = "No active Chatwoot connection found"
            event.processed_at = utc_now()
            return

        try:
            from app.services.chatwoot_client import send_message
            send_message(
                base_url=connection["base_url"],
                account_id=connection["account_id"],
                conversation_display_id=event.conversation_display_id,
                content=_HARDCODED_REPLY,
                agent_bot_token=connection["agent_bot_token"],
                agent_bot_id=connection["agent_bot_id"],
            )
            event.status = "processed"
            event.processed_at = utc_now()
            logger.info("process_chatwoot_event: event %s replied and processed", event_id)
        except Exception as exc:
            logger.exception("process_chatwoot_event: failed to send reply for event %s", event_id)
            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                event.status = "failed"
                event.error_message = str(exc)
                event.processed_at = utc_now()


def _resolve_connection(db, account_id: int | None, inbox_id: int | None) -> dict | None:
    """
    Find the active Chatwoot connection for this account + inbox.
    Falls back to env vars for local dev before a connection row is created via the UI.
    """
    if account_id is not None and inbox_id is not None:
        conn = db.scalar(
            select(ChatwootConnection).where(
                ChatwootConnection.status == "active",
                ChatwootConnection.chatwoot_account_id == account_id,
                ChatwootConnection.chatwoot_inbox_id == inbox_id,
            )
        )
        if conn:
            return {
                "base_url": conn.chatwoot_base_url,
                "account_id": conn.chatwoot_account_id,
                "agent_bot_id": conn.chatwoot_agent_bot_id,
                "agent_bot_token": conn.chatwoot_agent_bot_token or "",
            }

    if settings.chatwoot_base_url and settings.chatwoot_agent_bot_token:
        return {
            "base_url": settings.chatwoot_base_url,
            "account_id": account_id or settings.chatwoot_account_id,
            "agent_bot_id": settings.chatwoot_agent_bot_id,
            "agent_bot_token": settings.chatwoot_agent_bot_token,
        }

    return None
