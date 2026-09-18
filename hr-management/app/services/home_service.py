from __future__ import annotations

from app.models import CurrentUser, HomeBalanceSummary, HomeSnapshot
from app.repositories.leave_types_repository import LeaveTypesRepository
from app.services.leaves_service import LeavesService

_RECENT_LEAVES_LIMIT = 5


class HomeService:
    """Backs the Employee's simplified `/home` page — deliberately not a
    cut-down DashboardService, see DashboardSnapshot's docstring.
    """

    def __init__(
        self, leaves_service: LeavesService, leave_types_repository: LeaveTypesRepository
    ):
        self._leaves = leaves_service
        self._leave_types = leave_types_repository

    def get_for_employee(self, current_user: CurrentUser) -> HomeSnapshot:
        if not current_user.employee_id:
            # An admin/manager with no employee profile hitting /home
            # directly gets an empty-but-valid snapshot, not a 500.
            return HomeSnapshot(has_employee_profile=False, balances=[], recent_leaves=[])

        leave_type_names = {
            leave_type.id: leave_type.name for leave_type in self._leave_types.list()
        }
        balances = [
            HomeBalanceSummary(
                leave_type_name=leave_type_names.get(balance.leave_type_id, balance.leave_type_id),
                remaining=balance.remaining,
            )
            for balance in self._leaves.list_balances(current_user)
        ]
        recent_leaves = self._leaves.list_my(current_user, limit=_RECENT_LEAVES_LIMIT)

        return HomeSnapshot(
            has_employee_profile=True, balances=balances, recent_leaves=recent_leaves
        )
