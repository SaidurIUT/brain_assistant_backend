from datetime import timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings
from app.core.datetime import utc_now

ALGORITHM = "HS256"
password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return password_hasher.check_needs_rehash(password_hash)


def create_access_token(*, subject: UUID, email: str, is_superuser: bool) -> tuple[str, str]:
    now = utc_now()
    jti = str(uuid4())
    payload: dict[str, Any] = {
        "sub": str(subject),
        "email": email,
        "is_superuser": is_superuser,
        "type": "access",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
        "jti": jti,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM), jti


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM], options={"require": ["exp", "sub", "type"]})


def hash_refresh_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()

