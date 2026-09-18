from __future__ import annotations

from datetime import date

from google.cloud import firestore

from app.core.exceptions import ResourceOutOfScopeError
from app.models import (
    CurrentUser,
    LeaveBalanceDocument,
    LeaveCreateRequest,
    LeaveDocument,
    LeaveStatus,
    LeaveTypeDocument,
    UserRole,
)
from app.repositories.base import increment_counter
from app.repositories.employees_repository import EmployeesRepository
from app.repositories.holidays_repository import HolidaysRepository
from app.repositories.leave_balances_repository import LeaveBalancesRepository
from app.repositories.leave_types_repository import LeaveTypesRepository
from app.repositories.leaves_repository import LeavesRepository
from app.services.notifications_service import NotificationsService
from app.services.working_days import working_days_between

_EMPLOYEE_LIST_LIMIT_FOR_MANAGER_BALANCES = 200
_LEAVES_PENDING_COUNTER = "leaves_pending"  # Dashboard KPI (Module 2)


class NoEmployeeProfileError(Exception):
    """Raised when the caller has no employee_id linked to their account —
    covers an admin with no employee record trying to act as "themselves."
    """


class LeaveTypeNotFoundError(Exception):
    def __init__(self, leave_type_id: str):
        self.leave_type_id = leave_type_id
        super().__init__(f"Leave type {leave_type_id} does not exist")


class InsufficientBalanceError(Exception):
    def __init__(self, leave_type_name: str, requested: int, remaining: int):
        self.leave_type_name = leave_type_name
        self.requested = requested
        self.remaining = remaining
        super().__init__(f"Requested {requested} days but only {remaining} remain")


class OverlappingLeaveError(Exception):
    def __init__(self, overlapping_leave_id: str):
        self.overlapping_leave_id = overlapping_leave_id
        super().__init__(f"Overlaps with approved leave {overlapping_leave_id}")


class LeaveAlreadyDecidedError(Exception):
    def __init__(self, leave_id: str, status: LeaveStatus):
        self.leave_id = leave_id
        self.status = status
        super().__init__(f"Leave {leave_id} is already {status.value}")


def _date_ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


class LeavesService:
    """Unlike Départements/Postes/Employees, this module's routes are not
    admin-only — authorization is enforced here using the caller's
    CurrentUser (role, employee_id, department_id), not a router-level
    require_role gate.
    """

    def __init__(
        self,
        db: firestore.Client,
        leaves_repository: LeavesRepository,
        leave_balances_repository: LeaveBalancesRepository,
        leave_types_repository: LeaveTypesRepository,
        holidays_repository: HolidaysRepository,
        employees_repository: EmployeesRepository,
        notifications_service: NotificationsService,
    ):
        self._db = db
        self._leaves = leaves_repository
        self._balances = leave_balances_repository
        self._leave_types = leave_types_repository
        self._holidays = holidays_repository
        self._employees = employees_repository
        self._notifications = notifications_service

    def list_leave_types(self) -> list[LeaveTypeDocument]:
        return self._leave_types.list()

    def _scope_check(self, current_user: CurrentUser, leave: LeaveDocument) -> None:
        if current_user.role == UserRole.ADMIN:
            return
        if current_user.role == UserRole.MANAGER:
            if leave.department_id != current_user.department_id:
                raise ResourceOutOfScopeError()
            return
        if leave.employee_id != current_user.employee_id:
            raise ResourceOutOfScopeError()

    def submit(self, current_user: CurrentUser, request: LeaveCreateRequest) -> LeaveDocument:
        if not current_user.employee_id:
            raise NoEmployeeProfileError()
        employee = self._employees.get_by_id(current_user.employee_id)
        if employee is None:
            raise NoEmployeeProfileError()

        leave_type = self._leave_types.get_by_id(request.leave_type_id)
        if leave_type is None:
            raise LeaveTypeNotFoundError(request.leave_type_id)

        holidays = self._holidays.list()
        working_days = working_days_between(request.start_date, request.end_date, holidays)

        if leave_type.is_deductible:
            year = request.start_date.year
            default_initial = leave_type.default_days_per_year or 0
            balance = self._balances.get_or_create(employee.id, leave_type.id, year, default_initial)
            if balance.remaining < working_days:
                raise InsufficientBalanceError(leave_type.name, working_days, balance.remaining)

        for other in self._leaves.list_approved_for_employee(employee.id):
            if _date_ranges_overlap(
                request.start_date, request.end_date, other.start_date.date(), other.end_date.date()
            ):
                raise OverlappingLeaveError(other.id)

        created = self._leaves.create(
            employee_id=employee.id,
            employee_name=f"{employee.first_name} {employee.last_name}",
            department_id=employee.department_id,
            leave_type_id=leave_type.id,
            leave_type_name=leave_type.name,
            start_date=request.start_date,
            end_date=request.end_date,
            working_days=working_days,
            reason=request.reason,
        )
        increment_counter(self._db, _LEAVES_PENDING_COUNTER, delta=1)
        self._notifications.notify_leave_submitted(created)
        return created

    def get(self, current_user: CurrentUser, leave_id: str) -> LeaveDocument | None:
        leave = self._leaves.get_by_id(leave_id)
        if leave is None:
            return None
        self._scope_check(current_user, leave)
        return leave

    def approve(self, current_user: CurrentUser, leave_id: str) -> LeaveDocument | None:
        leave = self._leaves.get_by_id(leave_id)
        if leave is None:
            return None
        self._scope_check(current_user, leave)
        if leave.status != LeaveStatus.PENDING:
            raise LeaveAlreadyDecidedError(leave_id, leave.status)

        leave_type = self._leave_types.get_by_id(leave.leave_type_id)
        is_deductible = leave_type.is_deductible if leave_type else False
        default_initial = (leave_type.default_days_per_year or 0) if leave_type else 0
        year = leave.start_date.year

        @firestore.transactional
        def _approve_txn(transaction: firestore.Transaction) -> None:
            # All reads before the first write, per the cahier des charges'
            # explicit Firestore transaction-ordering constraint.
            leave_doc_ref, _ = self._leaves.read_within_transaction(transaction, leave_id)
            if is_deductible:
                balance_doc_ref, balance_snapshot = self._balances.read_within_transaction(
                    transaction, leave.employee_id, leave.leave_type_id, year
                )

            self._leaves.apply_approval_within_transaction(
                transaction, leave_doc_ref, decided_by=current_user.id
            )
            if is_deductible:
                self._balances.apply_usage_within_transaction(
                    transaction,
                    balance_doc_ref,
                    balance_snapshot,
                    employee_id=leave.employee_id,
                    leave_type_id=leave.leave_type_id,
                    year=year,
                    default_initial=default_initial,
                    delta_used=leave.working_days,
                )

        _approve_txn(self._db.transaction())
        increment_counter(self._db, _LEAVES_PENDING_COUNTER, delta=-1)
        updated = self._leaves.get_by_id(leave_id)
        self._notifications.notify_leave_decided(updated)
        return updated

    def reject(self, current_user: CurrentUser, leave_id: str, reason: str) -> LeaveDocument | None:
        leave = self._leaves.get_by_id(leave_id)
        if leave is None:
            return None
        self._scope_check(current_user, leave)
        if leave.status != LeaveStatus.PENDING:
            raise LeaveAlreadyDecidedError(leave_id, leave.status)
        updated = self._leaves.reject(leave_id, reason=reason, decided_by=current_user.id)
        increment_counter(self._db, _LEAVES_PENDING_COUNTER, delta=-1)
        self._notifications.notify_leave_decided(updated)
        return updated

    def list_my(
        self, current_user: CurrentUser, cursor_id: str | None = None, limit: int = 25
    ) -> list[LeaveDocument]:
        if not current_user.employee_id:
            return []
        return self._leaves.list(
            employee_id=current_user.employee_id, cursor_id=cursor_id, limit=limit
        )

    def list_pending(
        self, current_user: CurrentUser, cursor_id: str | None = None, limit: int = 25
    ) -> list[LeaveDocument]:
        return self._list_scoped(current_user, status=LeaveStatus.PENDING, cursor_id=cursor_id, limit=limit)

    def list_all(
        self, current_user: CurrentUser, cursor_id: str | None = None, limit: int = 25
    ) -> list[LeaveDocument]:
        return self._list_scoped(current_user, status=None, cursor_id=cursor_id, limit=limit)

    def _list_scoped(
        self,
        current_user: CurrentUser,
        *,
        status: LeaveStatus | None,
        cursor_id: str | None,
        limit: int,
    ) -> list[LeaveDocument]:
        if current_user.role == UserRole.ADMIN:
            return self._leaves.list(status=status, cursor_id=cursor_id, limit=limit)
        if current_user.role == UserRole.MANAGER:
            return self._leaves.list(
                department_id=current_user.department_id,
                status=status,
                cursor_id=cursor_id,
                limit=limit,
            )
        # Defense in depth: the router already blocks EMPLOYEE from these
        # two routes with require_role, but scope to "self only" here too
        # rather than trusting the router alone.
        return self._leaves.list(
            employee_id=current_user.employee_id, status=status, cursor_id=cursor_id, limit=limit
        )

    def list_balances(self, current_user: CurrentUser) -> list[LeaveBalanceDocument]:
        if current_user.role == UserRole.ADMIN:
            return self._balances.list_all()
        if current_user.role == UserRole.MANAGER:
            employees = self._employees.list(
                department_id=current_user.department_id,
                limit=_EMPLOYEE_LIST_LIMIT_FOR_MANAGER_BALANCES,
            )
            balances: list[LeaveBalanceDocument] = []
            for employee in employees:
                balances.extend(self._balances.list_for_employee(employee.id))
            return balances
        if not current_user.employee_id:
            return []
        return self._balances.list_for_employee(current_user.employee_id)

    def summary_for_employee(
        self, employee_id: str
    ) -> tuple[list[LeaveDocument], list[LeaveBalanceDocument]]:
        """Recent leave requests and current balances for one specific
        employee — used by the employee-profile "Congés" tab. Distinct from
        list_my/list_all/list_balances above, which are scoped to the
        *caller's* role rather than an arbitrary employee_id.
        """
        recent_leaves = self._leaves.list(employee_id=employee_id, limit=5)
        balances = self._balances.list_for_employee(employee_id)
        return recent_leaves, balances
