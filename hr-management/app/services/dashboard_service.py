from __future__ import annotations

from datetime import date, timedelta

from google.cloud import firestore

from app.models import (
    ContractType,
    CurrentUser,
    DashboardSnapshot,
    EmployeeDocument,
    EmployeeStatus,
    TrialPeriodDocument,
)
from app.repositories.base import get_counter_value
from app.repositories.departments_repository import DepartmentsRepository
from app.repositories.employees_repository import EmployeesRepository
from app.services.leaves_service import LeavesService
from app.services.trial_periods_service import TrialPeriodsService

_CONTRACTS_EXPIRING_WINDOW_DAYS = 30
_INTERNS_ENDING_WINDOW_DAYS = 15
_TRIAL_PERIODS_ENDING_WINDOW_DAYS = 15
_DISTRIBUTION_LIMIT = 250
_MANAGER_LIST_LIMIT = 250

_EMPLOYEES_ACTIVE_COUNTER = "employees_active"
_INTERNS_COUNTER = "interns"
_LEAVES_PENDING_COUNTER = "leaves_pending"
_DEPARTMENTS_ACTIVE_COUNTER = "departments_active"


class DashboardService:
    def __init__(
        self,
        db: firestore.Client,
        employees_repository: EmployeesRepository,
        departments_repository: DepartmentsRepository,
        leaves_service: LeavesService,
        trial_periods_service: TrialPeriodsService,
    ):
        self._db = db
        self._employees = employees_repository
        self._departments = departments_repository
        self._leaves = leaves_service
        self._trial_periods = trial_periods_service

    def get_for_admin(self) -> DashboardSnapshot:
        return self._build(department_id=None, current_user=None)

    def get_for_manager(self, current_user: CurrentUser) -> DashboardSnapshot:
        return self._build(department_id=current_user.department_id, current_user=current_user)

    def _build(
        self, *, department_id: str | None, current_user: CurrentUser | None
    ) -> DashboardSnapshot:
        today = date.today()

        # The department/contract-type distribution fetch is reused for the
        # manager's "employés actifs"/"stagiaires" counts too, instead of a
        # second query — see list_for_distribution's docstring for why this
        # one is a bounded fetch rather than a counter.
        distribution_employees = self._employees.list_for_distribution(
            department_id=department_id, limit=_DISTRIBUTION_LIMIT
        )
        active_only = [e for e in distribution_employees if e.status != EmployeeStatus.INACTIVE]

        if department_id is None:
            employees_active = get_counter_value(self._db, _EMPLOYEES_ACTIVE_COUNTER)
            interns = get_counter_value(self._db, _INTERNS_COUNTER)
            leaves_pending = get_counter_value(self._db, _LEAVES_PENDING_COUNTER)
            departments_active = get_counter_value(self._db, _DEPARTMENTS_ACTIVE_COUNTER)
        else:
            department = self._departments.get_by_id(department_id)
            employees_active = department.employee_count if department else 0
            interns = sum(1 for e in active_only if e.contract_type == ContractType.STAGE)
            assert current_user is not None  # manager path always supplies one
            leaves_pending = len(
                self._leaves.list_pending(current_user, limit=_MANAGER_LIST_LIMIT)
            )
            departments_active = None

        contracts_expiring = self._employees.list_contracts_expiring_within(
            _CONTRACTS_EXPIRING_WINDOW_DAYS, department_id=department_id
        )
        interns_ending_soon = [
            employee
            for employee in self._employees.list_contracts_expiring_within(
                _INTERNS_ENDING_WINDOW_DAYS, department_id=department_id
            )
            if employee.contract_type == ContractType.STAGE
        ]
        birthdays_this_month = self._employees.list_birthdays_this_month(
            today.month, department_id=department_id
        )
        new_hires_this_month = self._employees.list_new_hires_since(
            today.replace(day=1), department_id=department_id
        )
        trial_periods_ending_soon = self._trial_periods_ending_soon(department_id, today)

        return DashboardSnapshot(
            employees_active=employees_active,
            interns=interns,
            leaves_pending=leaves_pending,
            departments_active=departments_active,
            contracts_expiring=contracts_expiring,
            interns_ending_soon=interns_ending_soon,
            trial_periods_ending_soon=trial_periods_ending_soon,
            birthdays_this_month=birthdays_this_month,
            new_hires_this_month=new_hires_this_month,
            department_distribution=_department_distribution(active_only),
            contract_type_distribution=_contract_type_distribution(active_only),
        )

    def _trial_periods_ending_soon(
        self, department_id: str | None, today: date
    ) -> list[TrialPeriodDocument]:
        # Filtered in-memory over a small, bounded set (current trial
        # periods == active headcount only) — see the implementation
        # plan's scope-decision note on why this doesn't need a new
        # denormalized field or composite index.
        cutoff = today + timedelta(days=_TRIAL_PERIODS_ENDING_WINDOW_DAYS)
        candidates = self._trial_periods.list_current(limit=_DISTRIBUTION_LIMIT)
        result = []
        for trial in candidates:
            if trial.effective_end_date.date() > cutoff:
                continue
            if department_id is not None:
                employee = self._employees.get_by_id(trial.employee_id)
                if employee is None or employee.department_id != department_id:
                    continue
            result.append(trial)
        return result


def _department_distribution(employees: list[EmployeeDocument]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for employee in employees:
        counts[employee.department_name] = counts.get(employee.department_name, 0) + 1
    return sorted(counts.items())


def _contract_type_distribution(employees: list[EmployeeDocument]) -> dict[str, int]:
    counts = {"CDI": 0, "CDD": 0, "STAGE": 0}
    for employee in employees:
        counts[employee.contract_type.value] = counts.get(employee.contract_type.value, 0) + 1
    return counts
