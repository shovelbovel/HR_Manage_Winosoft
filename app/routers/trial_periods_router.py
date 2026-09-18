from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.core.dependencies import CurrentUserDep, get_trial_periods_service, require_role
from app.core.http import read_body, wants_json
from app.core.templating import templates
from app.models import ContractType, TrialPeriodDecisionRequest, TrialPeriodDocument, UserRole
from app.services.trial_periods_service import (
    TrialPeriodActionNotAllowedError,
    TrialPeriodNotRenewableError,
    TrialPeriodsService,
)

router = APIRouter(
    prefix="/trials",
    tags=["trial-periods"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)

_PAGE_SIZE_DEFAULT = 25


def _progress_percent(trial: TrialPeriodDocument) -> int:
    start = trial.start_date.date()
    end = trial.effective_end_date.date()
    today = datetime.now(timezone.utc).date()
    total_days = (end - start).days
    if total_days <= 0:
        return 100
    elapsed_days = (today - start).days
    return max(0, min(100, round(elapsed_days / total_days * 100)))


def _decision_error_message(exc: Exception) -> str:
    if isinstance(exc, TrialPeriodNotRenewableError):
        return "Ce type de contrat ne permet pas de prolongation de la période d'essai."
    if isinstance(exc, TrialPeriodActionNotAllowedError):
        return f"Cette action n'est plus possible (statut actuel : {exc.current_status.value})."
    return "Action invalide."


@router.get("")
def list_current_trial_periods(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[TrialPeriodsService, Depends(get_trial_periods_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    trials = service.list_current(cursor_id=cursor, limit=limit)
    if wants_json(request):
        return trials
    next_cursor = trials[-1].id if len(trials) == limit else None
    rows = [(trial, _progress_percent(trial)) for trial in trials]
    return templates.TemplateResponse(
        request,
        "trials/list.html",
        {
            "current_user": current_user,
            "rows": rows,
            "history": False,
            "next_cursor": next_cursor,
            "error": None,
        },
    )


@router.get("/history")
def list_trial_period_history(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[TrialPeriodsService, Depends(get_trial_periods_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    trials = service.list_history(cursor_id=cursor, limit=limit)
    if wants_json(request):
        return trials
    next_cursor = trials[-1].id if len(trials) == limit else None
    rows = [(trial, None) for trial in trials]
    return templates.TemplateResponse(
        request,
        "trials/list.html",
        {
            "current_user": current_user,
            "rows": rows,
            "history": True,
            "next_cursor": next_cursor,
            "error": None,
        },
    )


@router.get("/{trial_period_id}")
def trial_period_detail(
    request: Request,
    trial_period_id: str,
    current_user: CurrentUserDep,
    service: Annotated[TrialPeriodsService, Depends(get_trial_periods_service)],
):
    trial = service.get(trial_period_id)
    if trial is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return trial

    can_decide = trial.status.value in ("pending", "extended")
    can_extend = can_decide and trial.status.value == "pending" and trial.contract_type == ContractType.CDI
    return templates.TemplateResponse(
        request,
        "trials/detail.html",
        {
            "current_user": current_user,
            "trial": trial,
            "progress_percent": _progress_percent(trial),
            "can_decide": can_decide,
            "can_extend": can_extend,
            "error": None,
        },
    )


@router.post("/{trial_period_id}/validate")
async def validate_trial_period(
    request: Request,
    trial_period_id: str,
    current_user: CurrentUserDep,
    service: Annotated[TrialPeriodsService, Depends(get_trial_periods_service)],
):
    payload = await read_body(request, TrialPeriodDecisionRequest)
    try:
        updated = service.validate(trial_period_id, current_user, payload.reason)
    except TrialPeriodActionNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_decision_error_message(exc)
        ) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return updated
    return RedirectResponse(f"/trials/{trial_period_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{trial_period_id}/extend")
async def extend_trial_period(
    request: Request,
    trial_period_id: str,
    current_user: CurrentUserDep,
    service: Annotated[TrialPeriodsService, Depends(get_trial_periods_service)],
):
    payload = await read_body(request, TrialPeriodDecisionRequest)
    try:
        updated = service.extend(trial_period_id, current_user, payload.reason)
    except (TrialPeriodActionNotAllowedError, TrialPeriodNotRenewableError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_decision_error_message(exc)
        ) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return updated
    return RedirectResponse(f"/trials/{trial_period_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{trial_period_id}/refuse")
async def refuse_trial_period(
    request: Request,
    trial_period_id: str,
    current_user: CurrentUserDep,
    service: Annotated[TrialPeriodsService, Depends(get_trial_periods_service)],
):
    payload = await read_body(request, TrialPeriodDecisionRequest)
    try:
        updated = service.refuse(trial_period_id, current_user, payload.reason)
    except TrialPeriodActionNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_decision_error_message(exc)
        ) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return updated
    return RedirectResponse(f"/trials/{trial_period_id}", status_code=status.HTTP_303_SEE_OTHER)
