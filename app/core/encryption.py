from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    key = urlsafe_b64encode(sha256(settings.secret_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored secret could not be decrypted") from exc
