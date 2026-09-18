from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.core.dependencies import CurrentUserDep, get_leaves_service, require_role
from app.core.http import flash_redirect, read_body, wants_json
from app.core.templating import templates
from app.models import LeaveCreateRequest, LeaveRejectRequest, UserRole
from app.services.leaves_service import (
    InsufficientBalanceError,
    LeaveAlreadyDecidedError,
    LeavesService,
    LeaveTypeNotFoundError,
    NoEmployeeProfileError,
    OverlappingLeaveError,
)

router = APIRouter(prefix="/leaves", tags=["leaves"])

_PAGE_SIZE_DEFAULT = 25
_MANAGER_OR_ADMIN = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER))


def _submit_error_message(exc: Exception) -> str:
    if isinstance(exc, NoEmployeeProfileError):
        return "Aucune fiche employé n'est associée à ce compte."
    if isinstance(exc, LeaveTypeNotFoundError):
        return "Le type de congé sélectionné n'existe pas."
    if isinstance(exc, InsufficientBalanceError):
        return (
            f"Solde insuffisant pour « {exc.leave_type_name} » : "
            f"{exc.requested} jour(s) demandé(s), {exc.remaining} restant(s)."
        )
    if isinstance(exc, OverlappingLeaveError):
        return "Cette période chevauche un congé déjà approuvé."
    return "Requête invalide."


@router.get("/types")
def list_leave_types(service: Annotated[LeavesService, Depends(get_leaves_service)]):
    return service.list_leave_types()


@router.get("/my")
def list_my_leaves(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[LeavesService, Depends(get_leaves_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    leaves = service.list_my(current_user, cursor_id=cursor, limit=limit)
    if wants_json(request):
        return leaves
    next_cursor = leaves[-1].id if len(leaves) == limit else None
    return templates.TemplateResponse(
        request,
        "leaves/list.html",
        {
            "leaves": leaves,
            "title": "Mes congés",
            "next_cursor": next_cursor,
            "show_employee_column": False,
            "show_decide_actions": False,
            "current_user": current_user,
            "error": None,
        },
    )


@router.get("/create")
def create_leave_page(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[LeavesService, Depends(get_leaves_service)],
):
    return templates.TemplateResponse(
        request,
        "leaves/create.html",
        {
            "leave_types": service.list_leave_types(),
            "current_user": current_user,
            "error": None,
        },
    )


@router.post("")
async def submit_leave(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[LeavesService, Depends(get_leaves_service)],
):
    json_wanted = wants_json(request)
    payload = await read_body(request, LeaveCreateRequest)

    try:
        leave = service.submit(current_user, payload)
    except (
        NoEmployeeProfileError,
        LeaveTypeNotFoundError,
        InsufficientBalanceError,
        OverlappingLeaveError,
    ) as exc:
        error = _submit_error_message(exc)
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if isinstance(exc, (NoEmployeeProfileError, LeaveTypeNotFoundError))
            else status.HTTP_409_CONFLICT
        )
        if json_wanted:
            raise HTTPException(status_code=status_code, detail=error) from exc
        return templates.TemplateResponse(
            request,
            "leaves/create.html",
            {
                "leave_types": service.list_leave_types(),
                "current_user": current_user,
                "error": error,
            },
            status_code=status_code,
        )

    if json_wanted:
        return leave
    return RedirectResponse("/leaves/my", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/pending", dependencies=[_MANAGER_OR_ADMIN])
def list_pending_leaves(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[LeavesService, Depends(get_leaves_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    leaves = service.list_pending(current_user, cursor_id=cursor, limit=limit)
    if wants_json(request):
        return leaves
    next_cursor = leaves[-1].id if len(leaves) == limit else None
    return templates.TemplateResponse(
        request,
        "leaves/list.html",
        {
            "leaves": leaves,
            "title": "Demandes en attente",
            "next_cursor": next_cursor,
            "show_employee_column": True,
            "show_decide_actions": True,
            "current_user": current_user,
            "error": None,
        },
    )


@router.get("/balances")
def list_balances(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[LeavesService, Depends(get_leaves_service)],
):
    balances = service.list_balances(current_user)
    if wants_json(request):
        return balances
    return templates.TemplateResponse(
        request,
        "leaves/balances.html",
        {"balances": balances, "current_user": current_user, "error": None},
    )


@router.get("", dependencies=[_MANAGER_OR_ADMIN])
def list_all_leaves(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[LeavesService, Depends(get_leaves_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    leaves = service.list_all(current_user, cursor_id=cursor, limit=limit)
    if wants_json(request):
        return leaves
    next_cursor = leaves[-1].id if len(leaves) == limit else None
    return templates.TemplateResponse(
        request,
        "leaves/list.html",
        {
            "leaves": leaves,
            "title": "Toutes les demandes",
            "next_cursor": next_cursor,
            "show_employee_column": True,
            "show_decide_actions": False,
            "current_user": current_user,
            "error": None,
        },
    )


@router.get("/{leave_id}")
def leave_detail(
    request: Request,
    leave_id: str,
    current_user: CurrentUserDep,
    service: Annotated[LeavesService, Depends(get_leaves_service)],
):
    # service.get raises ResourceOutOfScopeError for a manager/employee
    # outside their scope — that propagates to the handler registered in
    # app.main (→ 404), the same stub wired up since the Module 1 scaffold.
    leave = service.get(current_user, leave_id)
    if leave is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return leave

    can_decide = current_user.role in (UserRole.ADMIN, UserRole.MANAGER) and (
        leave.status.value == "pending"
    )
    return templates.TemplateResponse(
        request,
        "leaves/detail.html",
        {"leave": leave, "can_decide": can_decide, "current_user": current_user, "error": None},
    )


@router.post("/{leave_id}/approve", dependencies=[_MANAGER_OR_ADMIN])
def approve_leave(
    request: Request,
    leave_id: str,
    current_user: CurrentUserDep,
    service: Annotated[LeavesService, Depends(get_leaves_service)],
):
    try:
        updated = service.approve(current_user, leave_id)
    except LeaveAlreadyDecidedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return updated
    return flash_redirect(f"/leaves/{leave_id}", "Demande de congé approuvée.", "success")


@router.post("/{leave_id}/reject", dependencies=[_MANAGER_OR_ADMIN])
async def reject_leave(
    request: Request,
    leave_id: str,
    current_user: CurrentUserDep,
    service: Annotated[LeavesService, Depends(get_leaves_service)],
):
    payload = await read_body(request, LeaveRejectRequest)
    try:
        updated = service.reject(current_user, leave_id, payload.reason)
    except LeaveAlreadyDecidedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return updated
    return flash_redirect(f"/leaves/{leave_id}", "Demande de congé refusée.", "warning")
