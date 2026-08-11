from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt
from jose import JWTError, jwt

from app.core.config import Settings, get_settings
from app.models import TokenPayload, UserRole


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired, or the wrong type."""


def hash_password(password: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed hash (e.g. empty string) — treat as a non-match rather
        # than raising, so callers can use this in a uniform failure path.
        return False


def _create_token(
    *,
    subject: str,
    token_type: Literal["access", "refresh"],
    expires_delta: timedelta,
    role: UserRole | None = None,
    employee_id: str | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role.value if role else None,
        "employee_id": employee_id,
        "token_type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(
    user_id: str,
    role: UserRole,
    employee_id: str | None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    return _create_token(
        subject=user_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
        role=role,
        employee_id=employee_id,
        settings=settings,
    )


def create_refresh_token(user_id: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    # Deliberately carries no role/employee_id: a stolen refresh token alone
    # cannot mint an elevated access token, only a fresh access token is
    # minted after re-reading the user's current role from Firestore.
    return _create_token(
        subject=user_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.jwt_refresh_token_expire_days),
        settings=settings,
    )


def decode_token(
    token: str,
    expected_type: Literal["access", "refresh"],
    settings: Settings | None = None,
) -> TokenPayload:
    settings = settings or get_settings()
    try:
        raw = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise TokenError("Invalid or expired token") from exc

    if raw.get("token_type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token")

    role = UserRole(raw["role"]) if raw.get("role") else None
    return TokenPayload(
        sub=raw["sub"],
        role=role,
        employee_id=raw.get("employee_id"),
        token_type=raw["token_type"],
        exp=raw["exp"],
    )
