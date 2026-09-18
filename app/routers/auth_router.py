from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core import security
from app.core.config import Settings, get_settings
from app.core.dependencies import get_auth_service
from app.core.http import read_body, wants_json
from app.core.templating import templates
from app.models import LoginRequest, TokenPair, UserRole
from app.services.auth_service import GENERIC_AUTH_ERROR, AuthService

router = APIRouter(tags=["auth"])

_REFRESH_COOKIE_PATH = "/refresh"


def _landing_page(role: UserRole) -> str:
    # Access matrix (page 11): "Tableau de bord complet" is Admin/Manager;
    # Employé gets the distinct "Page d'accueil simplifiée" instead.
    return "/home" if role == UserRole.EMPLOYEE else "/dashboard"


def _set_auth_cookies(response: Response, token_pair: TokenPair, settings: Settings) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token_pair.access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
        max_age=settings.jwt_access_token_expire_minutes * 60,
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token_pair.refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=_REFRESH_COOKIE_PATH,
        max_age=settings.jwt_refresh_token_expire_days * 24 * 60 * 60,
    )


@router.get("/login")
def login_page(request: Request, settings: Annotated[Settings, Depends(get_settings)]):
    token = request.cookies.get(settings.cookie_name)
    if token:
        try:
            payload = security.decode_token(token, expected_type="access", settings=settings)
        except security.TokenError:
            pass
        else:
            # payload.role is always set on an access token in practice
            # (create_access_token always supplies one) — "/dashboard" is
            # just a defensive fallback, never expected to trigger.
            landing = _landing_page(payload.role) if payload.role else "/dashboard"
            return RedirectResponse(url=landing, status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "auth/login.html", {"error": None})


@router.post("/login")
async def login_submit(
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    json_wanted = wants_json(request)
    credentials = await read_body(request, LoginRequest)

    result = auth_service.authenticate(credentials.email, credentials.password)

    if not result.success or result.user is None:
        if json_wanted:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_ERROR
            )
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": GENERIC_AUTH_ERROR},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token_pair = auth_service.issue_token_pair(result.user)

    if json_wanted:
        return token_pair

    response = RedirectResponse(url=_landing_page(result.user.role), status_code=status.HTTP_303_SEE_OTHER)
    _set_auth_cookies(response, token_pair, settings)
    return response


@router.post("/logout")
def logout(settings: Annotated[Settings, Depends(get_settings)]):
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(settings.cookie_name, path="/")
    response.delete_cookie(settings.refresh_cookie_name, path=_REFRESH_COOKIE_PATH)
    return response


@router.post("/refresh")
def refresh(
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        access_token = auth_service.refresh_access_token(refresh_token)
    except security.TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        ) from exc

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        key=settings.cookie_name,
        value=access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
        max_age=settings.jwt_access_token_expire_minutes * 60,
    )
    return response
