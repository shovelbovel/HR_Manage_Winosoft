from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import (
    CurrentUserDep,
    get_dashboard_service,
    get_home_service,
    get_settings_service,
    require_role,
)
from app.core.http import wants_json
from app.core.templating import templates
from app.models import UserRole
from app.services.dashboard_service import DashboardService
from app.services.home_service import HomeService
from app.services.settings_service import SettingsService

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", dependencies=[Depends(require_role(UserRole.ADMIN, UserRole.MANAGER))])
def dashboard(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[DashboardService, Depends(get_dashboard_service)],
    settings_service: Annotated[SettingsService, Depends(get_settings_service)],
):
    snapshot = (
        service.get_for_admin()
        if current_user.role == UserRole.ADMIN
        else service.get_for_manager(current_user)
    )
    if wants_json(request):
        return snapshot
    ai_settings = settings_service.get_ai()
    return templates.TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "current_user": current_user,
            "snapshot": snapshot,
            "ai_enabled": bool(ai_settings and ai_settings.enabled),
        },
    )


@router.get("/home")
def home(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[HomeService, Depends(get_home_service)],
):
    snapshot = service.get_for_employee(current_user)
    if wants_json(request):
        return snapshot
    return templates.TemplateResponse(
        request, "home/index.html", {"current_user": current_user, "snapshot": snapshot}
    )
