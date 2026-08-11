from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from google.cloud import firestore

from app.core import security
from app.core.config import Settings, get_settings
from app.core.firestore_client import get_firestore_client
from app.models import CurrentUser, UserRole
from app.repositories.users_repository import UsersRepository
from app.services.auth_service import AuthService


def get_settings_dependency() -> Settings:
    return get_settings()


def get_db() -> firestore.Client:
    return get_firestore_client()


def get_users_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> UsersRepository:
    return UsersRepository(db)


def get_auth_service(
    users_repository: Annotated[UsersRepository, Depends(get_users_repository)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> AuthService:
    return AuthService(users_repository, settings)


def get_token_from_request(request: Request, settings: Settings) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:]
    return request.cookies.get(settings.cookie_name)


def get_current_user(
    request: Request,
    users_repository: Annotated[UsersRepository, Depends(get_users_repository)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> CurrentUser:
    token = get_token_from_request(request, settings)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = security.decode_token(token, expected_type="access", settings=settings)
    except security.TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        ) from exc

    # Re-fetch from Firestore and re-check is_active on every request: this
    # is what makes deactivating a user take effect immediately rather than
    # at token expiry, per the cahier des charges' "Révocation" rule.
    user = users_repository.get_by_id(payload.sub)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    return CurrentUser(id=user.id, email=user.email, role=user.role, employee_id=user.employee_id)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(*roles: UserRole):
    """Dependency factory: 403s if the caller isn't one of `roles`.

    This guards "are you logged in with the right role at all." It is a
    different concern from the cahier des charges' "404 not 403" rule, which
    is about per-resource scope cloisonnement (e.g. a manager reading an
    employee outside their department) — that check belongs in the
    service/repository query logic of the module owning the resource, not
    here.
    """

    def _check(current_user: CurrentUserDep) -> CurrentUser:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return current_user

    return _check
