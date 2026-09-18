from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.core.dependencies import (
    CurrentUserDep,
    get_departments_service,
    get_positions_service,
    require_role,
)
from app.core.http import flash_redirect, read_body, wants_json
from app.core.templating import templates
from app.models import PositionCreateRequest, PositionUpdateRequest, UserRole
from app.services.departments_service import DepartmentsService
from app.services.positions_service import (
    DepartmentNotFoundError,
    PositionNotEmptyError,
    PositionsService,
)

router = APIRouter(
    prefix="/positions",
    tags=["positions"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)

_PAGE_SIZE = 25
_DEPARTMENT_PICKER_LIMIT = 100


@router.get("")
def list_positions(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[PositionsService, Depends(get_positions_service)],
    department_id: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
):
    positions = service.list(department_id=department_id, cursor_id=cursor, limit=_PAGE_SIZE)
    if wants_json(request):
        return positions

    next_cursor = positions[-1].id if len(positions) == _PAGE_SIZE else None
    return templates.TemplateResponse(
        request,
        "positions/list.html",
        {
            "current_user": current_user,
            "positions": positions,
            "next_cursor": next_cursor,
            "department_id": department_id,
            "error": None,
        },
    )


@router.get("/create")
def create_position_page(
    request: Request,
    current_user: CurrentUserDep,
    departments_service: Annotated[DepartmentsService, Depends(get_departments_service)],
):
    departments = departments_service.list(cursor_id=None, limit=_DEPARTMENT_PICKER_LIMIT)
    return templates.TemplateResponse(
        request,
        "positions/form.html",
        {"current_user": current_user, "position": None, "departments": departments, "error": None},
    )


@router.post("")
async def create_position(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[PositionsService, Depends(get_positions_service)],
    departments_service: Annotated[DepartmentsService, Depends(get_departments_service)],
):
    json_wanted = wants_json(request)
    payload = await read_body(request, PositionCreateRequest)

    try:
        position = service.create(payload.department_id, payload.title, payload.max_occupants)
    except DepartmentNotFoundError as exc:
        error = "Le département sélectionné n'existe pas."
        if json_wanted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error) from exc
        departments = departments_service.list(cursor_id=None, limit=_DEPARTMENT_PICKER_LIMIT)
        return templates.TemplateResponse(
            request,
            "positions/form.html",
            {"current_user": current_user, "position": None, "departments": departments, "error": error},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if json_wanted:
        return position
    return RedirectResponse(f"/positions/{position.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{position_id}")
def position_detail(
    request: Request,
    position_id: str,
    current_user: CurrentUserDep,
    service: Annotated[PositionsService, Depends(get_positions_service)],
    departments_service: Annotated[DepartmentsService, Depends(get_departments_service)],
):
    position = service.get(position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return position
    departments = departments_service.list(cursor_id=None, limit=_DEPARTMENT_PICKER_LIMIT)
    return templates.TemplateResponse(
        request,
        "positions/form.html",
        {"current_user": current_user, "position": position, "departments": departments, "error": None},
    )


@router.post("/{position_id}")
async def update_position(
    request: Request,
    position_id: str,
    service: Annotated[PositionsService, Depends(get_positions_service)],
):
    position = service.get(position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    payload = await read_body(request, PositionUpdateRequest)
    updated = service.update(position_id, payload.title, payload.max_occupants)

    if wants_json(request):
        return updated
    return RedirectResponse(f"/positions/{position_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{position_id}/delete")
def delete_position(
    request: Request,
    position_id: str,
    current_user: CurrentUserDep,
    service: Annotated[PositionsService, Depends(get_positions_service)],
):
    json_wanted = wants_json(request)
    try:
        deleted = service.delete(position_id)
    except PositionNotEmptyError as exc:
        error = f"Ce poste a encore {exc.occupant_count} occupant(s)."
        if json_wanted:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error) from exc
        positions = service.list(department_id=None, cursor_id=None, limit=_PAGE_SIZE)
        return templates.TemplateResponse(
            request,
            "positions/list.html",
            {
                "current_user": current_user,
                "positions": positions,
                "next_cursor": None,
                "department_id": None,
                "error": error,
            },
            status_code=status.HTTP_409_CONFLICT,
        )

    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if json_wanted:
        return {"status": "deleted"}
    return flash_redirect("/positions", "Poste supprimé.", "success")
