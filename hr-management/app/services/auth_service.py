from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core import security
from app.core.config import Settings, get_settings
from app.models import TokenPair, UserDocument
from app.repositories.users_repository import UsersRepository

# Wall-clock budget every authenticate() call is padded up to, regardless of
# which branch it takes (unknown email, wrong password, locked account).
# Chosen comfortably above a single bcrypt verify at cost 12 on modest
# hardware; tune if BCRYPT_ROUNDS changes. This equalizes response time
# alongside the identical error message, per the cahier des charges'
# anti-enumeration requirement ("le temps de réponse est égalisé").
_AUTH_TIME_BUDGET_SECONDS = 0.35

GENERIC_AUTH_ERROR = "Identifiants invalides ou compte temporairement bloqué."


@dataclass
class AuthResult:
    success: bool
    user: UserDocument | None = None


class AuthService:
    def __init__(self, users_repository: UsersRepository, settings: Settings | None = None):
        self._users = users_repository
        self._settings = settings or get_settings()

    def authenticate(self, email: str, password: str) -> AuthResult:
        started_at = time.monotonic()
        try:
            return self._authenticate(email, password)
        finally:
            elapsed = time.monotonic() - started_at
            remaining = _AUTH_TIME_BUDGET_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def _authenticate(self, email: str, password: str) -> AuthResult:
        user = self._users.get_by_email(email)
        if user is None:
            return AuthResult(success=False)

        if not user.is_active:
            return AuthResult(success=False)

        if user.locked_until is not None:
            locked_until = _as_aware_utc(user.locked_until)
            if locked_until > datetime.now(timezone.utc):
                return AuthResult(success=False)

        if not security.verify_password(password, user.hashed_password):
            attempts = self._users.increment_failed_attempts(user.id)
            if attempts >= self._settings.login_max_failed_attempts:
                locked_until = datetime.now(timezone.utc) + timedelta(
                    minutes=self._settings.login_lockout_minutes
                )
                self._users.set_lockout(user.id, locked_until)
            return AuthResult(success=False)

        self._users.reset_failed_attempts(user.id)
        self._users.touch_last_login(user.id)
        return AuthResult(success=True, user=user)

    def issue_token_pair(self, user: UserDocument) -> TokenPair:
        return TokenPair(
            access_token=security.create_access_token(
                user.id, user.role, user.employee_id, settings=self._settings
            ),
            refresh_token=security.create_refresh_token(user.id, settings=self._settings),
        )

    def refresh_access_token(self, refresh_token: str) -> str:
        payload = security.decode_token(refresh_token, expected_type="refresh")
        # The refresh token carries no role — the caller's current role and
        # active status are always re-read from Firestore before minting a
        # new access token, never trusted from the token itself.
        user = self._users.get_by_id(payload.sub)
        if user is None or not user.is_active:
            raise security.TokenError("User is no longer active")
        return security.create_access_token(
            user.id, user.role, user.employee_id, settings=self._settings
        )


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
