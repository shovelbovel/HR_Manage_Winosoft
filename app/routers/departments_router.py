from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.core.dependencies import CurrentUserDep, get_departments_service, require_role
from app.core.http import flash_redirect, read_body, wants_json
from app.core.templating import templates
from app.models import DepartmentCreateRequest, DepartmentUpdateRequest, UserRole
from app.repositories.base import AlreadyExistsError
from app.services.departments_service import DepartmentNotEmptyError, DepartmentsService

router = APIRouter(
    prefix="/departments",
    tags=["departments"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)

_PAGE_SIZE = 25


@router.get("")
def list_departments(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[DepartmentsService, Depends(get_departments_service)],
    cursor: Annotated[str | None, Query()] = None,
):
    departments = service.list(cursor_id=cursor, limit=_PAGE_SIZE)
    if wants_json(request):
        return departments

    next_cursor = departments[-1].id if len(departments) == _PAGE_SIZE else None
    return templates.TemplateResponse(
        request,
        "departments/list.html",
        {
            "current_user": current_user,
            "departments": departments,
            "next_cursor": next_cursor,
            "error": None,
        },
    )


@router.get("/create")
def create_department_page(request: Request, current_user: CurrentUserDep):
    return templates.TemplateResponse(
        request, "departments/form.html", {"current_user": current_user, "department": None, "error": None}
    )


@router.post("")
async def create_department(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[DepartmentsService, Depends(get_departments_service)],
):
    json_wanted = wants_json(request)
    payload = await read_body(request, DepartmentCreateRequest)

    try:
        department = service.create(payload.code, payload.name)
    except AlreadyExistsError as exc:
        error = f"Le code « {payload.code} » est déjà utilisé."
        if json_wanted:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error) from exc
        return templates.TemplateResponse(
            request,
            "departments/form.html",
            {"current_user": current_user, "department": None, "error": error},
            status_code=status.HTTP_409_CONFLICT,
        )

    if json_wanted:
        return department
    return RedirectResponse(f"/departments/{department.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{department_id}")
def department_detail(
    request: Request,
    department_id: str,
    current_user: CurrentUserDep,
    service: Annotated[DepartmentsService, Depends(get_departments_service)],
):
    department = service.get(department_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return department
    return templates.TemplateResponse(
        request,
        "departments/form.html",
        {"current_user": current_user, "department": department, "error": None},
    )


@router.post("/{department_id}")
async def update_department(
    request: Request,
    department_id: str,
    service: Annotated[DepartmentsService, Depends(get_departments_service)],
):
    department = service.get(department_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    payload = await read_body(request, DepartmentUpdateRequest)
    updated = service.rename(department_id, payload.name)

    if wants_json(request):
        return updated
    return RedirectResponse(f"/departments/{department_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{department_id}/delete")
def delete_department(
    request: Request,
    department_id: str,
    current_user: CurrentUserDep,
    service: Annotated[DepartmentsService, Depends(get_departments_service)],
):
    json_wanted = wants_json(request)
    try:
        deleted = service.delete(department_id)
    except DepartmentNotEmptyError as exc:
        error = f"Ce département contient encore {exc.employee_count} employé(s)."
        if json_wanted:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error) from exc
        departments = service.list(cursor_id=None, limit=_PAGE_SIZE)
        return templates.TemplateResponse(
            request,
            "departments/list.html",
            {
                "current_user": current_user,
                "departments": departments,
                "next_cursor": None,
                "error": error,
            },
            status_code=status.HTTP_409_CONFLICT,
        )

    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if json_wanted:
        return {"status": "deleted"}
    return flash_redirect("/departments", "Département supprimé.", "success")
