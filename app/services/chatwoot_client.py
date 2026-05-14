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
