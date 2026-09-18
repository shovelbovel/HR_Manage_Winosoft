from __future__ import annotations

from datetime import date

from app.models import (
    ContractType,
    CurrentUser,
    EmployeeDocument,
    EmployeeStatus,
    TrialPeriodDocument,
    TrialPeriodStatus,
)
from app.repositories.employees_repository import EmployeesRepository
from app.repositories.trial_periods_repository import TrialPeriodsRepository
from app.services.trial_period_calculation import calculate_initial_trial_end_date

_CURRENT_STATUSES = (TrialPeriodStatus.PENDING, TrialPeriodStatus.EXTENDED)
_HISTORY_STATUSES = (TrialPeriodStatus.VALIDATED, TrialPeriodStatus.REFUSED)


class TrialPeriodActionNotAllowedError(Exception):
    """Raised when validate/extend/refuse is attempted on a trial period
    that isn't in a status the action supports (e.g. refusing an already
    validated trial). Maps to 409."""

    def __init__(self, trial_period_id: str, action: str, current_status: TrialPeriodStatus):
        self.trial_period_id = trial_period_id
        self.action = action
        self.current_status = current_status
        super().__init__(
            f"Cannot {action} trial period {trial_period_id} in status {current_status.value}"
        )


class TrialPeriodNotRenewableError(Exception):
    """Raised when extend is attempted on a non-CDI trial period — the
    cahier des charges' renewal column is "Non" for CDD and Stage has no
    programmatic renewal in this pass (see implementation plan)."""

    def __init__(self, trial_period_id: str, contract_type: ContractType):
        self.trial_period_id = trial_period_id
        self.contract_type = contract_type
        super().__init__(f"Trial period {trial_period_id} ({contract_type.value}) is not renewable")


class TrialPeriodsService:
    def __init__(
        self,
        repository: TrialPeriodsRepository,
        employees_repository: EmployeesRepository,
    ):
        self._repository = repository
        self._employees = employees_repository

    def create_for_employee(
        self, employee: EmployeeDocument, trial_end_date_override: date | None
    ) -> TrialPeriodDocument:
        start_date = employee.hire_date.date()
        initial_end_date = calculate_initial_trial_end_date(
            contract_type=employee.contract_type,
            contract_category=employee.contract_category,
            start_date=start_date,
            contract_end_date=(
                employee.contract_end_date.date() if employee.contract_end_date else None
            ),
            override=trial_end_date_override,
        )
        return self._repository.create(
            employee_id=employee.id,
            contract_type=employee.contract_type,
            contract_category=employee.contract_category,
            start_date=start_date,
            initial_end_date=initial_end_date,
        )

    def get_for_employee(self, employee_id: str) -> TrialPeriodDocument | None:
        return self._repository.get_by_employee_id(employee_id)

    def get(self, trial_period_id: str) -> TrialPeriodDocument | None:
        return self._repository.get_by_id(trial_period_id)

    def list_current(
        self, cursor_id: str | None = None, limit: int = 25
    ) -> list[TrialPeriodDocument]:
        return self._repository.list(_CURRENT_STATUSES, cursor_id=cursor_id, limit=limit)

    def list_history(
        self, cursor_id: str | None = None, limit: int = 25
    ) -> list[TrialPeriodDocument]:
        return self._repository.list(_HISTORY_STATUSES, cursor_id=cursor_id, limit=limit)

    def validate(
        self, trial_period_id: str, current_user: CurrentUser, reason: str
    ) -> TrialPeriodDocument | None:
        trial = self._repository.get_by_id(trial_period_id)
        if trial is None:
            return None
        if trial.status not in _CURRENT_STATUSES:
            raise TrialPeriodActionNotAllowedError(trial_period_id, "validate", trial.status)

        updated = self._repository.decide(
            trial_period_id,
            status=TrialPeriodStatus.VALIDATED,
            decided_by=current_user.id,
            reason=reason,
        )
        # The one place a trial-period decision drives the employee's own
        # status without needing the Cloud-Functions-dependent
        # auto-transition (see Module 3's documented gap).
        self._employees.set_status(trial.employee_id, EmployeeStatus.ACTIVE)
        return updated

    def extend(
        self, trial_period_id: str, current_user: CurrentUser, reason: str
    ) -> TrialPeriodDocument | None:
        trial = self._repository.get_by_id(trial_period_id)
        if trial is None:
            return None
        if trial.contract_type != ContractType.CDI:
            raise TrialPeriodNotRenewableError(trial_period_id, trial.contract_type)
        if trial.status != TrialPeriodStatus.PENDING:
            # Covers both "already extended once" (only one renewal
            # allowed) and "already validated/refused".
            raise TrialPeriodActionNotAllowedError(trial_period_id, "extend", trial.status)

        initial_duration = trial.initial_end_date.date() - trial.start_date.date()
        new_end_date = trial.initial_end_date.date() + initial_duration
        return self._repository.decide(
            trial_period_id,
            status=TrialPeriodStatus.EXTENDED,
            decided_by=current_user.id,
            reason=reason,
            extended_end_date=new_end_date,
        )

    def refuse(
        self, trial_period_id: str, current_user: CurrentUser, reason: str
    ) -> TrialPeriodDocument | None:
        trial = self._repository.get_by_id(trial_period_id)
        if trial is None:
            return None
        if trial.status not in _CURRENT_STATUSES:
            raise TrialPeriodActionNotAllowedError(trial_period_id, "refuse", trial.status)

        # Deliberately doesn't touch employee.status — refusing a trial is
        # a precursor to a termination process Modules 3/7 don't model yet
        # (documented, not a silent gap).
        return self._repository.decide(
            trial_period_id,
            status=TrialPeriodStatus.REFUSED,
            decided_by=current_user.id,
            reason=reason,
        )
