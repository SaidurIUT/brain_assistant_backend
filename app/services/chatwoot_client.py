import logging

import httpx

logger = logging.getLogger(__name__)


def send_message(
    *,
    base_url: str,
    account_id: int,
    conversation_display_id: int,
    content: str,
    agent_bot_token: str,
    agent_bot_id: int,
) -> None:
    """
    Post a message to a Chatwoot conversation as the AgentBot.

    Uses conversation_display_id (the #N shown in the UI) — this is what the
    Chatwoot messages API expects in the URL path, confirmed from:
        app/controllers/api/v1/accounts/conversations/base_controller.rb
        → find_by!(display_id: params[:conversation_id])
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_display_id}/messages"
    )
    payload = {
        "content": content,
        "message_type": "outgoing",
        "sender_type": "AgentBot",
        "sender_id": agent_bot_id,
    }
    logger.info("Sending reply to conversation %d", conversation_display_id)
    response = httpx.post(
        url,
        json=payload,
        headers={"api_access_token": agent_bot_token},
        timeout=10,
    )
    response.raise_for_status()
    logger.info("Reply sent, status=%d", response.status_code)


def send_typing_status(
    *,
    base_url: str,
    account_id: int,
    conversation_display_id: int,
    agent_bot_token: str,
    typing_on: bool,
) -> None:
    """
    Toggle the 'Bot is typing…' indicator in the Chatwoot conversation.
    Best-effort — errors are logged but never raised so a typing failure
    can't break the reply pipeline.
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_display_id}/toggle_typing_status"
    )
    try:
        response = httpx.post(
            url,
            json={"typing_status": "on" if typing_on else "off"},
            headers={"api_access_token": agent_bot_token},
            timeout=5,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to set typing_status=%s: %s", typing_on, exc)


def set_conversation_status(
    *,
    base_url: str,
    account_id: int,
    conversation_display_id: int,
    agent_bot_token: str,
    status: str,
) -> None:
    """
    Flip a conversation's status (open / pending / resolved / snoozed).

    Used by the handoff flow to flip 'pending' → 'open' so the conversation
    shows up in the agent's normal Open queue. Best-effort: failures are
    logged but never raised so a status flip can't break the reply pipeline.
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_display_id}/toggle_status"
    )
    try:
        response = httpx.post(
            url,
            json={"status": status},
            headers={"api_access_token": agent_bot_token},
            timeout=5,
        )
        response.raise_for_status()
        logger.info(
            "Conversation %d status set to %s", conversation_display_id, status
        )
    except Exception as exc:
        logger.warning(
            "Failed to set status=%s on conversation %d: %s",
            status,
            conversation_display_id,
            exc,
        )


def send_private_note(
    *,
    base_url: str,
    account_id: int,
    conversation_display_id: int,
    agent_bot_token: str,
    agent_bot_id: int,
    content: str,
) -> None:
    """
    Post a private note (agent-only visible) to a conversation.

    Same /messages endpoint as send_message, but with private=True — the
    customer never sees it. Used on handoff to give the agent quick context
    on what the customer asked and why the bot couldn't answer.
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_display_id}/messages"
    )
    payload = {
        "content": content,
        "message_type": "outgoing",
        "private": True,
        "sender_type": "AgentBot",
        "sender_id": agent_bot_id,
    }
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"api_access_token": agent_bot_token},
            timeout=10,
        )
        response.raise_for_status()
        logger.info("Private note posted to conversation %d", conversation_display_id)
    except Exception as exc:
        logger.warning(
            "Failed to post private note on conversation %d: %s",
            conversation_display_id,
            exc,
        )


def add_conversation_labels(
    *,
    base_url: str,
    account_id: int,
    conversation_display_id: int,
    agent_bot_token: str,
    labels: list[str],
) -> None:
    """
    Add labels to a Chatwoot conversation for triage and analytics.

    Labels are merged with whatever's already on the conversation — Chatwoot's
    API uses POST semantics that replace, so we fetch current labels first
    and union. Best-effort: failures don't break the reply pipeline.
    """
    base = (
        f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_display_id}/labels"
    )
    headers = {"api_access_token": agent_bot_token}
    try:
        existing_resp = httpx.get(base, headers=headers, timeout=5)
        existing_resp.raise_for_status()
        existing = set(existing_resp.json().get("payload", []))
        merged = sorted(existing | set(labels))
        response = httpx.post(
            base,
            json={"labels": merged},
            headers=headers,
            timeout=5,
        )
        response.raise_for_status()
        logger.info(
            "Labels %s applied to conversation %d", merged, conversation_display_id
        )
    except Exception as exc:
        logger.warning(
            "Failed to set labels=%s on conversation %d: %s",
            labels,
            conversation_display_id,
            exc,
        )


def fetch_conversation_messages(
    *,
    base_url: str,
    account_id: int,
    conversation_display_id: int,
    agent_bot_token: str,
    limit: int = 10,
) -> list[dict]:
    """
    Return the last N messages of a conversation, oldest-first.
    Empty list on any failure so the caller can still proceed with just the current message.

    Each item: {"sender": "contact"|"agent"|"bot", "content": "..."}
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}"
        f"/conversations/{conversation_display_id}/messages"
    )
    try:
        response = httpx.get(
            url,
            headers={"api_access_token": agent_bot_token},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json().get("payload", [])
    except Exception as exc:
        logger.warning("Failed to fetch conversation history: %s", exc)
        return []

    # Chatwoot returns newest-first; reverse so context reads chronologically
    messages = []
    for m in reversed(payload[:limit]):
        sender_type = (m.get("sender_type") or "").lower()
        if sender_type == "contact":
            role = "contact"
        elif sender_type == "agentbot":
            role = "bot"
        else:
            role = "agent"
        content = m.get("content") or ""
        if content.strip():
            messages.append({"sender": role, "content": content})
    return messages
