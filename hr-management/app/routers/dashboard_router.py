from fastapi import APIRouter, Request

from app.core.dependencies import CurrentUserDep
from app.core.templating import templates

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(request: Request, current_user: CurrentUserDep):
    return templates.TemplateResponse(
        request, "dashboard/index.html", {"current_user": current_user}
    )
