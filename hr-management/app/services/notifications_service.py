from __future__ import annotations

from app.models import (
    CurrentUser,
    EmployeeDocument,
    LeaveDocument,
    LeaveStatus,
    NotificationCategory,
    NotificationDocument,
    NotificationRecentResponse,
)
from app.repositories.notifications_repository import NotificationsRepository
from app.repositories.users_repository import UsersRepository

_RECENT_LIMIT = 10


class NotificationsService:
    def __init__(self, repository: NotificationsRepository, users_repository: UsersRepository):
        self._repository = repository
        self._users = users_repository

    def list_recent(self, current_user: CurrentUser) -> NotificationRecentResponse:
        return NotificationRecentResponse(
            unread_count=self._repository.count_unread(current_user.id),
            notifications=self._repository.list_recent(current_user.id, limit=_RECENT_LIMIT),
        )

    def list_all(
        self, current_user: CurrentUser, cursor_id: str | None = None, limit: int = 25
    ) -> list[NotificationDocument]:
        return self._repository.list_all(current_user.id, cursor_id=cursor_id, limit=limit)

    def mark_read(
        self, notification_id: str, current_user: CurrentUser
    ) -> NotificationDocument | None:
        notification = self._repository.get_by_id(notification_id)
        if notification is None or notification.recipient_user_id != current_user.id:
            # Ownership violation reported the same way as "doesn't exist" —
            # never confirms another user's notification exists, same
            # 404-not-403 reasoning as ResourceOutOfScopeError elsewhere.
            return None
        if notification.is_read:
            return notification
        return self._repository.mark_read(notification_id)

    def mark_all_read(self, current_user: CurrentUser) -> None:
        self._repository.mark_all_read(current_user.id)

    def _department_recipients(self, department_id: str) -> list[str]:
        managers = self._users.list_active_managers_for_department(department_id)
        admins = self._users.list_admins()
        return [user.id for user in managers] + [user.id for user in admins]

    def notify_leave_submitted(self, leave: LeaveDocument) -> None:
        self._repository.create_many(
            recipient_user_ids=self._department_recipients(leave.department_id),
            category=NotificationCategory.LEAVE_PENDING,
            message=f"Nouvelle demande de congé de {leave.employee_name}",
            link=f"/leaves/{leave.id}",
        )

    def notify_leave_decided(self, leave: LeaveDocument) -> None:
        recipient = self._users.get_by_employee_id(leave.employee_id)
        if recipient is None:
            return  # no login account linked to this employee (Module 11 gap)
        verb = "approuvée" if leave.status == LeaveStatus.APPROVED else "refusée"
        self._repository.create(
            recipient_user_id=recipient.id,
            category=NotificationCategory.LEAVE_DECISION,
            message=f"Votre demande de congé ({leave.leave_type_name}) a été {verb}",
            link=f"/leaves/{leave.id}",
        )

    def notify_new_employee(self, employee: EmployeeDocument) -> None:
        self._repository.create_many(
            recipient_user_ids=self._department_recipients(employee.department_id),
            category=NotificationCategory.NEW_EMPLOYEE,
            message=(
                f"Nouvel employé : {employee.first_name} {employee.last_name} "
                f"({employee.department_name})"
            ),
            link=f"/employees/{employee.id}",
        )
