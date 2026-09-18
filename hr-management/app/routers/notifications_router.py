from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse

from app.core.dependencies import CurrentUserDep, get_notifications_service
from app.core.http import wants_json
from app.core.templating import templates
from app.services.notifications_service import NotificationsService

router = APIRouter(prefix="/notifications", tags=["notifications"])

_PAGE_SIZE_DEFAULT = 25
_DEFAULT_REDIRECT = "/notifications"


@router.get("/recent")
def recent_notifications(
    current_user: CurrentUserDep,
    service: Annotated[NotificationsService, Depends(get_notifications_service)],
):
    # AJAX-only: powers the navbar bell's badge + dropdown. Always JSON,
    # there is no HTML page at this URL.
    return service.list_recent(current_user)


@router.post("/mark-all-read")
def mark_all_read(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[NotificationsService, Depends(get_notifications_service)],
):
    service.mark_all_read(current_user)
    if wants_json(request):
        return {"status": "ok"}
    return RedirectResponse(url=_DEFAULT_REDIRECT, status_code=status.HTTP_303_SEE_OTHER)


@router.get("")
def list_notifications(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[NotificationsService, Depends(get_notifications_service)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    notifications = service.list_all(current_user, cursor_id=cursor, limit=limit)
    if wants_json(request):
        return notifications
    next_cursor = notifications[-1].id if len(notifications) == limit else None
    return templates.TemplateResponse(
        request,
        "notifications/index.html",
        {"current_user": current_user, "notifications": notifications, "next_cursor": next_cursor},
    )


@router.post("/{notification_id}/read")
def mark_read(
    request: Request,
    notification_id: str,
    current_user: CurrentUserDep,
    service: Annotated[NotificationsService, Depends(get_notifications_service)],
):
    updated = service.mark_read(notification_id, current_user)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if wants_json(request):
        return updated
    # The bell dropdown marks-as-read via a fire-and-forget sendBeacon and
    # navigates client-side to the notification's own link; this HTML form
    # path is only reached from the full /notifications page's own
    # "Marquer comme lu" button, which should stay on that page.
    return RedirectResponse(url=_DEFAULT_REDIRECT, status_code=status.HTTP_303_SEE_OTHER)
