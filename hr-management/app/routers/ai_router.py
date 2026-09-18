from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse

from app.core.ai_client import AIServiceUnavailableError
from app.core.dependencies import (
    CurrentUserDep,
    get_ai_service,
    get_dashboard_service,
    require_role,
)
from app.core.http import read_body, wants_json
from app.core.templating import templates
from app.models import DraftRequest, DraftResponse, UserRole
from app.services.ai_service import (
    AIDisabledError,
    AIQuotaExceededError,
    AIService,
    UnsupportedFileTypeError,
)
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/ai", tags=["ai"])

_MAX_CV_SIZE_BYTES = 5 * 1024 * 1024  # 5 Mo, per the cahier des charges

_FALLBACK_MESSAGE = (
    "L'assistant est momentanément indisponible. Merci de saisir les informations "
    "manuellement."
)
_DISABLED_MESSAGE = "L'assistant intelligent n'est pas activé pour le moment."
_QUOTA_MESSAGE = "Le quota d'appels à l'assistant est atteint. Réessayez plus tard."


def _error_status_and_message(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, AIDisabledError):
        return status.HTTP_403_FORBIDDEN, _DISABLED_MESSAGE
    if isinstance(exc, AIQuotaExceededError):
        return status.HTTP_429_TOO_MANY_REQUESTS, _QUOTA_MESSAGE
    if isinstance(exc, UnsupportedFileTypeError):
        return (
            status.HTTP_400_BAD_REQUEST,
            "Format de fichier non pris en charge (PDF ou DOCX uniquement).",
        )
    return status.HTTP_503_SERVICE_UNAVAILABLE, _FALLBACK_MESSAGE  # AIServiceUnavailableError


@router.get("/import-cv", dependencies=[Depends(require_role(UserRole.ADMIN))])
def import_cv_page(request: Request, current_user: CurrentUserDep):
    return templates.TemplateResponse(
        request, "ai/import_cv.html", {"current_user": current_user, "error": None}
    )


@router.post("/import-cv", dependencies=[Depends(require_role(UserRole.ADMIN))])
async def import_cv(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[AIService, Depends(get_ai_service)],
    file: Annotated[UploadFile, File()],
):
    json_wanted = wants_json(request)
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_CV_SIZE_BYTES:
        error = "Le fichier dépasse la taille maximale de 5 Mo."
        if json_wanted:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
        return templates.TemplateResponse(
            request,
            "ai/import_cv.html",
            {"current_user": current_user, "error": error},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        fields = service.extract_cv(current_user.id, file_bytes, file.content_type or "")
    except (
        AIDisabledError,
        AIQuotaExceededError,
        UnsupportedFileTypeError,
        AIServiceUnavailableError,
    ) as exc:
        status_code, error = _error_status_and_message(exc)
        if json_wanted:
            raise HTTPException(status_code=status_code, detail=error) from exc
        return templates.TemplateResponse(
            request,
            "ai/import_cv.html",
            {"current_user": current_user, "error": error},
            status_code=status_code,
        )

    if json_wanted:
        return fields

    query = {
        key: str(value)
        for key, value in fields.model_dump(exclude_none=True).items()
    }
    return RedirectResponse(
        url=f"/employees/create?{urlencode(query)}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/draft", dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.MANAGER))])
def draft_page(request: Request, current_user: CurrentUserDep):
    return templates.TemplateResponse(
        request, "ai/draft.html", {"current_user": current_user, "error": None, "result": None}
    )


@router.post("/draft", dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.MANAGER))])
async def create_draft(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[AIService, Depends(get_ai_service)],
):
    json_wanted = wants_json(request)
    payload = await read_body(request, DraftRequest)
    try:
        result: DraftResponse = service.generate_draft(current_user.id, payload)
    except (AIDisabledError, AIQuotaExceededError, AIServiceUnavailableError) as exc:
        status_code, error = _error_status_and_message(exc)
        if json_wanted:
            raise HTTPException(status_code=status_code, detail=error) from exc
        return templates.TemplateResponse(
            request,
            "ai/draft.html",
            {"current_user": current_user, "error": error, "result": None},
            status_code=status_code,
        )

    if json_wanted:
        return result
    return templates.TemplateResponse(
        request, "ai/draft.html", {"current_user": current_user, "error": None, "result": result.text}
    )


@router.get("/summary", dependencies=[Depends(require_role(UserRole.ADMIN))])
def dashboard_summary(
    request: Request,
    current_user: CurrentUserDep,
    ai_service: Annotated[AIService, Depends(get_ai_service)],
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
):
    json_wanted = wants_json(request)
    # Fetched outside the try block: the charts/stat cards built from this
    # snapshot should still render even if the AI text call itself fails —
    # the underlying data isn't an "AI" concern, only the commentary is.
    snapshot = dashboard_service.get_for_admin()
    try:
        text = ai_service.summarize_dashboard(current_user.id, snapshot)
    except (AIDisabledError, AIQuotaExceededError, AIServiceUnavailableError) as exc:
        status_code, error = _error_status_and_message(exc)
        if json_wanted:
            raise HTTPException(status_code=status_code, detail=error) from exc
        return templates.TemplateResponse(
            request,
            "ai/summary.html",
            {"current_user": current_user, "snapshot": snapshot, "error": error, "text": None},
            status_code=status_code,
        )

    if json_wanted:
        return {"text": text, "snapshot": snapshot}
    return templates.TemplateResponse(
        request,
        "ai/summary.html",
        {"current_user": current_user, "snapshot": snapshot, "error": None, "text": text},
    )
