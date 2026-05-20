from app.core.config import settings
from app.core.datetime import utc_now
from app.models import User


def _user(email_verified_at=None) -> User:
    return User(
        email="member@example.com",
        email_normalized="member@example.com",
        first_name="Member",
        last_name="User",
        password_hash="hash",
        email_verified_at=email_verified_at,
    )


def test_local_auth_uses_backend_email_verification_state(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_provider", "local")

    assert _user().email_verified is False
    assert _user(email_verified_at=utc_now()).email_verified is True


def test_keycloak_auth_trusts_identity_provider_when_strict_verification_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_provider", "keycloak")
    monkeypatch.setattr(settings, "keycloak_require_verified_email", False)

    assert _user().email_verified is True


def test_keycloak_auth_can_require_keycloak_verified_claim(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_provider", "keycloak")
    monkeypatch.setattr(settings, "keycloak_require_verified_email", True)

    assert _user().email_verified is False
    assert _user(email_verified_at=utc_now()).email_verified is True
