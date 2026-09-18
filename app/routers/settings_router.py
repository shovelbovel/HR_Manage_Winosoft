from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.core.dependencies import (
    CurrentUserDep,
    get_ai_audit_log_repository,
    get_settings_service,
    require_role,
)
from app.core.http import flash_redirect, read_body, wants_json
from app.core.templating import templates
from app.models import (
    AISettingsUpdateRequest,
    CompanySettingsUpdateRequest,
    HolidayCreateRequest,
    LeaveTypeCreateRequest,
    LeaveTypeUpdateRequest,
    UserCreateRequest,
    UserPasswordResetRequest,
    UserRole,
)
from app.repositories.ai_audit_log_repository import AIAuditLogRepository
from app.repositories.base import AlreadyExistsError
from app.services.settings_service import EmployeeNotFoundError, SettingsService

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)

_PAGE_SIZE_DEFAULT = 25


@router.get("/company")
def company_settings_page(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    company = service.get_company()
    if wants_json(request):
        return company
    return templates.TemplateResponse(
        request,
        "settings/company.html",
        {"current_user": current_user, "company": company, "error": None},
    )


@router.post("/company")
async def update_company_settings(
    request: Request,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    payload = await read_body(request, CompanySettingsUpdateRequest)
    company = service.set_company(payload)
    if wants_json(request):
        return company
    return RedirectResponse(url="/settings/company", status_code=status.HTTP_303_SEE_OTHER)


# -- Congés ---------------------------------------------------------------


@router.get("/leaves")
def leaves_settings_page(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    leave_types = service.list_leave_types()
    holidays = service.list_holidays()
    if wants_json(request):
        return {"leave_types": leave_types, "holidays": holidays}
    return templates.TemplateResponse(
        request,
        "settings/leaves.html",
        {"current_user": current_user, "leave_types": leave_types, "holidays": holidays, "error": None},
    )


@router.post("/leaves/leave-types")
async def create_leave_type(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    json_wanted = wants_json(request)
    payload = await read_body(request, LeaveTypeCreateRequest)
    try:
        leave_type = service.create_leave_type(payload)
    except AlreadyExistsError as exc:
        error = f"Le code « {payload.code} » est déjà utilisé."
        if json_wanted:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error) from exc
        leave_types = service.list_leave_types()
        holidays = service.list_holidays()
        return templates.TemplateResponse(
            request,
            "settings/leaves.html",
            {
                "current_user": current_user,
                "leave_types": leave_types,
                "holidays": holidays,
                "error": error,
            },
            status_code=status.HTTP_409_CONFLICT,
        )

    if json_wanted:
        return leave_type
    return RedirectResponse(url="/settings/leaves", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/leaves/leave-types/{leave_type_id}")
async def update_leave_type(
    request: Request,
    leave_type_id: str,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    payload = await read_body(request, LeaveTypeUpdateRequest)
    leave_type = service.update_leave_type(leave_type_id, payload)
    if leave_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if wants_json(request):
        return leave_type
    return RedirectResponse(url="/settings/leaves", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/leaves/holidays")
async def create_holiday(
    request: Request,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    payload = await read_body(request, HolidayCreateRequest)
    holiday = service.create_holiday(payload)
    if wants_json(request):
        return holiday
    return RedirectResponse(url="/settings/leaves", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/leaves/holidays/{holiday_id}/delete")
def delete_holiday(
    request: Request,
    holiday_id: str,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    service.delete_holiday(holiday_id)
    if wants_json(request):
        return {"status": "deleted"}
    return flash_redirect("/settings/leaves", "Jour férié supprimé.", "success")


# -- Utilisateurs -----------------------------------------------------------


@router.get("/users")
def list_users_page(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[SettingsService, Depends(get_settings_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    users = service.list_users(cursor_id=cursor, limit=limit)
    if wants_json(request):
        return users
    next_cursor = users[-1].id if len(users) == limit else None
    return templates.TemplateResponse(
        request,
        "settings/users_list.html",
        {"current_user": current_user, "users": users, "next_cursor": next_cursor},
    )


@router.get("/users/create")
def create_user_page(request: Request, current_user: CurrentUserDep):
    return templates.TemplateResponse(
        request, "settings/users_create.html", {"current_user": current_user, "error": None}
    )


@router.post("/users")
async def create_user(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    json_wanted = wants_json(request)
    payload = await read_body(request, UserCreateRequest)
    try:
        user = service.create_user(payload)
    except AlreadyExistsError as exc:
        error = f"L'email « {payload.email} » est déjà utilisé."
        status_code = status.HTTP_409_CONFLICT
        if json_wanted:
            raise HTTPException(status_code=status_code, detail=error) from exc
        return templates.TemplateResponse(
            request,
            "settings/users_create.html",
            {"current_user": current_user, "error": error},
            status_code=status_code,
        )
    except EmployeeNotFoundError as exc:
        error = "Employé introuvable."
        status_code = status.HTTP_404_NOT_FOUND
        if json_wanted:
            raise HTTPException(status_code=status_code, detail=error) from exc
        return templates.TemplateResponse(
            request,
            "settings/users_create.html",
            {"current_user": current_user, "error": error},
            status_code=status_code,
        )

    if json_wanted:
        return user
    return RedirectResponse(url=f"/settings/users/{user.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/users/{user_id}")
def user_detail_page(
    request: Request,
    user_id: str,
    current_user: CurrentUserDep,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    user = service.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if wants_json(request):
        return user
    return templates.TemplateResponse(
        request,
        "settings/users_detail.html",
        {"current_user": current_user, "target_user": user, "error": None},
    )


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    request: Request,
    user_id: str,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    payload = await read_body(request, UserPasswordResetRequest)
    user = service.reset_user_password(user_id, payload)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if wants_json(request):
        return user
    return flash_redirect(f"/settings/users/{user_id}", "Mot de passe réinitialisé.", "success")


@router.post("/users/{user_id}/activate")
def activate_user(
    request: Request,
    user_id: str,
    current_user: CurrentUserDep,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    json_wanted = wants_json(request)
    try:
        user = service.activate_user(user_id)
    except AlreadyExistsError as exc:
        error = "Cet email a été repris par un autre compte entre-temps."
        status_code = status.HTTP_409_CONFLICT
        if json_wanted:
            raise HTTPException(status_code=status_code, detail=error) from exc
        target_user = service.get_user(user_id)
        return templates.TemplateResponse(
            request,
            "settings/users_detail.html",
            {"current_user": current_user, "target_user": target_user, "error": error},
            status_code=status_code,
        )

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if json_wanted:
        return user
    return flash_redirect(f"/settings/users/{user_id}", "Compte réactivé.", "success")


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    request: Request,
    user_id: str,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    user = service.deactivate_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if wants_json(request):
        return user
    return flash_redirect(f"/settings/users/{user_id}", "Compte désactivé.", "success")


# -- Assistant (Module 12) ---------------------------------------------------


@router.get("/ai")
def ai_settings_page(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[SettingsService, Depends(get_settings_service)],
    audit_log_repository: Annotated[AIAuditLogRepository, Depends(get_ai_audit_log_repository)],
):
    ai_settings = service.get_ai()
    recent_calls = audit_log_repository.list_recent(limit=25)
    if wants_json(request):
        return {"settings": ai_settings, "recent_calls": recent_calls}
    return templates.TemplateResponse(
        request,
        "settings/ai.html",
        {"current_user": current_user, "ai_settings": ai_settings, "recent_calls": recent_calls},
    )


@router.post("/ai")
async def update_ai_settings(
    request: Request,
    service: Annotated[SettingsService, Depends(get_settings_service)],
):
    payload = await read_body(request, AISettingsUpdateRequest)
    ai_settings = service.set_ai(payload)
    if wants_json(request):
        return ai_settings
    return RedirectResponse(url="/settings/ai", status_code=status.HTTP_303_SEE_OTHER)
