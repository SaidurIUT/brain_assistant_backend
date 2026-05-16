import logging
import re
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.datetime import utc_now
from app.db.session import get_worker_db
from app.models.chatwoot import ChatwootConnection, ChatwootEvent
from app.workers.celery_app import celery

logger = logging.getLogger(__name__)

_FALLBACK_REPLY = "Thanks for your message. I will get back to you shortly."
_FAILURE_REPLY = "I'm having trouble answering right now. A team member will follow up with you soon."
_HANDOFF_REPLY = (
    "I'm not certain about that — let me get a teammate to help. "
    "They'll be in touch shortly."
)

# How many prior messages to include as context for the RAG query
_HISTORY_LIMIT = 8


def _choose_reply(query_result, cleaner) -> str:
    """Pure: map a QueryResult into the customer-facing string.

    Three distinct outcomes for clear agent triage:
      - not confident      → handoff (no relevant context found)
      - confident + empty  → fallback (LLM returned nothing despite context)
      - confident + answer → cleaned LightRAG answer
    """
    if not query_result.confident:
        return _HANDOFF_REPLY
    cleaned = cleaner(query_result.answer or "")
    if not cleaned.strip():
        return _FALLBACK_REPLY
    return cleaned


def _build_question_with_history(history: list[dict], current_message: str) -> str:
    """
    Build a context-aware query for RAG by prepending recent conversation turns.
    If there's no history, just return the current message verbatim.
    """
    if not history:
        return current_message

    turns = []
    for msg in history[-_HISTORY_LIMIT:]:
        speaker = "Customer" if msg["sender"] == "contact" else "Assistant"
        turns.append(f"{speaker}: {msg['content']}")

    return (
        "Recent conversation so far:\n"
        + "\n".join(turns)
        + f"\n\nNow the customer asks: {current_message}\n"
        + "Answer the customer's latest question using the knowledge base."
    )


def _clean_reply(reply: str) -> str:
    """
    LightRAG answers come back with markdown sections like '### Answer' and
    '### References'. For a chat widget we want just the answer text — strip
    the references block and any leftover ### headers.
    """
    if not reply or not reply.strip():
        return reply

    # Prefer the explicit Answer section if the LLM produced one
    for header in ("Answer", "Content & Grounding"):
        match = re.search(
            rf"^###\s*{re.escape(header)}\s*\n+(.+?)(?=^###\s+|\Z)",
            reply, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE,
        )
        if match:
            return match.group(1).strip()

    # Otherwise drop the References block and any standalone ### headers
    cleaned = re.sub(
        r"^###\s*References\s*\n.*?(?=^###\s+|\Z)",
        "", reply, flags=re.DOTALL | re.IGNORECASE | re.MULTILINE,
    )
    cleaned = re.sub(r"^###\s+.*$\n*", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


@celery.task(bind=True, max_retries=3, default_retry_delay=30)
def process_chatwoot_event(self, event_id: str) -> None:
    """
    Process a stored ChatwootEvent after ingestion.

    For incoming customer messages:
      - Resolve the active Chatwoot connection for this account + inbox
      - Post a reply back to Chatwoot via the AgentBot API
      - Mark the event processed

    Outgoing messages (bot replies firing back as webhooks) are skipped to
    prevent infinite loops.
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

        from app.services.chatwoot_client import (
            fetch_conversation_messages,
            send_message,
            send_typing_status,
        )
        from app.services.rag_service import sync_query_with_confidence

        send_typing_status(
            base_url=connection["base_url"],
            account_id=connection["account_id"],
            conversation_display_id=event.conversation_display_id,
            agent_bot_token=connection["agent_bot_token"],
            typing_on=True,
        )

        try:
            history = fetch_conversation_messages(
                base_url=connection["base_url"],
                account_id=connection["account_id"],
                conversation_display_id=event.conversation_display_id,
                agent_bot_token=connection["agent_bot_token"],
                limit=_HISTORY_LIMIT,
            )
            # Drop the latest message from history since event.content is already it
            prior_history = [m for m in history if m["content"] != (event.content or "")]
            question = _build_question_with_history(prior_history, event.content or "")

            query_result = sync_query_with_confidence(question)
            reply = _choose_reply(query_result, _clean_reply)

            send_message(
                base_url=connection["base_url"],
                account_id=connection["account_id"],
                conversation_display_id=event.conversation_display_id,
                content=reply,
                agent_bot_token=connection["agent_bot_token"],
                agent_bot_id=connection["agent_bot_id"],
            )

            event.reply_content = reply
            event.status = "processed"
            event.processed_at = utc_now()
            logger.info(
                "process_chatwoot_event: event=%s confident=%s chunks=%d outcome=%s",
                event_id,
                query_result.confident,
                query_result.chunk_count,
                "handoff" if not query_result.confident else "answer",
            )

        except Exception as exc:
            logger.exception("process_chatwoot_event: failed to send reply for event %s", event_id)
            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                # Out of retries — send a user-facing failure message so the customer isn't ignored
                try:
                    send_message(
                        base_url=connection["base_url"],
                        account_id=connection["account_id"],
                        conversation_display_id=event.conversation_display_id,
                        content=_FAILURE_REPLY,
                        agent_bot_token=connection["agent_bot_token"],
                        agent_bot_id=connection["agent_bot_id"],
                    )
                    event.reply_content = _FAILURE_REPLY
                except Exception as send_exc:
                    logger.warning("Could not send failure-state message: %s", send_exc)
                event.status = "failed"
                event.error_message = str(exc)
                event.processed_at = utc_now()

        finally:
            send_typing_status(
                base_url=connection["base_url"],
                account_id=connection["account_id"],
                conversation_display_id=event.conversation_display_id,
                agent_bot_token=connection["agent_bot_token"],
                typing_on=False,
            )


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
