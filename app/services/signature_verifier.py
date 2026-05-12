import hashlib
import hmac


def verify(*, raw_body: bytes, timestamp: str, signature: str, secret: str) -> bool:
    """
    Verify a Chatwoot AgentBot webhook signature.

    Chatwoot signs every request with:
        sha256=HMAC_SHA256(secret, "{timestamp}.{raw_body}")
    Source: lib/webhooks/trigger.rb

    Must use raw request bytes — not parsed JSON — because JSON serialisation
    is non-deterministic and would produce a different byte string.

    Uses hmac.compare_digest to prevent timing attacks.
    """
    if not all([raw_body, timestamp, signature, secret]):
        return False

    message = f"{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
    expected_digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    expected = f"sha256={expected_digest}"

    return hmac.compare_digest(expected, signature)
