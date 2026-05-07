import pytest
from pydantic import ValidationError

from app.schemas.auth import RegisterRequest


def test_register_password_requires_match() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="person@example.com",
            first_name="Person",
            last_name="Example",
            password="StrongPassword1!",
            confirm_password="DifferentPassword1!",
        )


def test_register_password_requires_strength() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="person@example.com",
            first_name="Person",
            last_name="Example",
            password="weakpassword",
            confirm_password="weakpassword",
        )

