"""
Extracts a flat, stable set of fields from a raw Chatwoot AgentBot webhook payload.

Chatwoot sends two structurally different payload shapes depending on event type:

MESSAGE EVENTS  (message_created, message_updated)
    payload["id"]                      → message DB id
    payload["account"]["id"]           → account id
    payload["inbox"]["id"]             → inbox id
    payload["conversation"]["id"]      → conversation DISPLAY id (not DB id)
    payload["message_type"]            → "incoming" | "outgoing" | "template"
    payload["sender"]                  → contacts have no "type" key — inferred from message_type
    payload["content"]                 → message text

CONVERSATION EVENTS  (conversation_updated, conversation_status_changed,
                       conversation_resolved, conversation_opened)
    payload["id"]                      → conversation DISPLAY id (not DB id)
    payload["inbox_id"]                → inbox id (flat)
    payload["contact_inbox"]["account"]["id"] → account id
    payload["meta"]["sender"]["type"]  → sender type
"""

_MESSAGE_EVENTS = frozenset({"message_created", "message_updated"})
_CONVERSATION_EVENTS = frozenset({
    "conversation_updated",
    "conversation_status_changed",
    "conversation_resolved",
    "conversation_opened",
})


def normalize(payload: dict, event_name: str) -> dict:
    """Return a flat dict of normalised fields for storage in chatwoot_events."""
    if event_name in _MESSAGE_EVENTS:
        return _from_message(payload)
    if event_name in _CONVERSATION_EVENTS:
        return _from_conversation(payload)
    return _generic(payload)


def _from_message(payload: dict) -> dict:
    sender = payload.get("sender") or {}
    message_type = payload.get("message_type")
    sender_type = sender.get("type") or ("contact" if message_type == "incoming" else None)

    return {
        "account_id": _dig(payload, "account", "id"),
        "inbox_id": _dig(payload, "inbox", "id"),
        "conversation_display_id": _dig(payload, "conversation", "id"),
        "message_id": payload.get("id"),
        "message_type": message_type,
        "sender_type": sender_type,
        "content": payload.get("content"),
    }


def _from_conversation(payload: dict) -> dict:
    return {
        "account_id": _dig(payload, "contact_inbox", "account", "id"),
        "inbox_id": payload.get("inbox_id"),
        "conversation_display_id": payload.get("id"),
        "message_id": None,
        "message_type": None,
        "sender_type": _dig(payload, "meta", "sender", "type"),
        "content": None,
    }


def _generic(payload: dict) -> dict:
    return {
        "account_id": _dig(payload, "account", "id"),
        "inbox_id": payload.get("inbox_id") or _dig(payload, "inbox", "id"),
        "conversation_display_id": _dig(payload, "conversation", "id") or payload.get("id"),
        "message_id": None,
        "message_type": None,
        "sender_type": _dig(payload, "sender", "type"),
        "content": payload.get("content"),
    }


def _dig(d: dict, *keys):
    for key in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d
