from __future__ import annotations

from google.cloud import firestore

from app.core import crypto
from app.models import (
    ContractType,
    EmployeeCreateRequest,
    EmployeeDocument,
    EmployeeStatus,
    EmployeeUpdateRequest,
)
from app.repositories.base import increment_counter
from app.repositories.departments_repository import DepartmentsRepository
from app.repositories.employees_repository import EmployeesRepository
from app.repositories.positions_repository import PositionsRepository
from app.services.departments_service import DepartmentNotFoundError
from app.services.notifications_service import NotificationsService
from app.services.positions_service import PositionNotFoundError
from app.services.trial_periods_service import TrialPeriodsService

# Dashboard KPI counters (Module 2). Business-decision-driven (activate()'s
# idempotency check, for one) so they're bumped here in the service, not
# inside EmployeesRepository — same reasoning already applied to
# department.employee_count/position.occupant_count below.
_EMPLOYEES_ACTIVE_COUNTER = "employees_active"
_INTERNS_COUNTER = "interns"


class PositionDepartmentMismatchError(Exception):
    """Raised when the chosen position doesn't belong to the chosen
    department — the spec's employee form filters positions by department
    precisely to prevent this, but the server must still enforce it since a
    client-side filter is not a security boundary."""

    def __init__(self, position_id: str, department_id: str):
        self.position_id = position_id
        self.department_id = department_id
        super().__init__(f"Position {position_id} does not belong to department {department_id}")


class PositionCapacityExceededError(Exception):
    """Raised when assigning an employee would exceed the position's
    max_occupants cap — the one place Module 5's optional cap is actually
    enforced (see PositionsRepository.increment_occupant_count's docstring).
    """

    def __init__(self, position_id: str, max_occupants: int):
        self.position_id = position_id
        self.max_occupants = max_occupants
        super().__init__(f"Position {position_id} is already at capacity ({max_occupants})")


class EmployeesService:
    def __init__(
        self,
        db: firestore.Client,
        repository: EmployeesRepository,
        departments_repository: DepartmentsRepository,
        positions_repository: PositionsRepository,
        trial_periods_service: TrialPeriodsService,
        notifications_service: NotificationsService,
    ):
        self._db = db
        self._repository = repository
        self._departments = departments_repository
        self._positions = positions_repository
        self._trial_periods = trial_periods_service
        self._notifications = notifications_service

    def create(self, request: EmployeeCreateRequest) -> EmployeeDocument:
        department = self._departments.get_by_id(request.department_id)
        if department is None:
            raise DepartmentNotFoundError(request.department_id)

        position = self._positions.get_by_id(request.position_id)
        if position is None:
            raise PositionNotFoundError(request.position_id)
        if position.department_id != request.department_id:
            raise PositionDepartmentMismatchError(request.position_id, request.department_id)
        if position.max_occupants is not None and position.occupant_count >= position.max_occupants:
            raise PositionCapacityExceededError(request.position_id, position.max_occupants)

        employee = self._repository.create(
            first_name=request.first_name,
            last_name=request.last_name,
            cin=request.cin,
            birth_date=request.birth_date,
            professional_email=request.professional_email,
            phone=request.phone,
            department_id=request.department_id,
            department_name=department.name,
            position_id=request.position_id,
            position_title=position.title,
            hire_date=request.hire_date,
            contract_type=request.contract_type,
            contract_category=request.contract_category,
            contract_start_date=request.contract_start_date,
            contract_end_date=request.contract_end_date,
            gross_salary_encrypted=crypto.encrypt(str(request.gross_salary)),
            rib_encrypted=crypto.encrypt(request.rib),
            cnss_number=request.cnss_number,
            emergency_contact_name=request.emergency_contact_name,
            emergency_contact_phone=request.emergency_contact_phone,
            internal_notes=request.internal_notes,
        )

        # "Aucun employé ne peut exister sans période d'essai associée"
        # (Module 8) — created as a sequential follow-up write, not the
        # same Firestore transaction as the employee doc; see the
        # implementation plan's scope-decision note on why (same
        # drift-tolerance already accepted for the counters below).
        self._trial_periods.create_for_employee(employee, request.trial_end_date_override)

        # Extension point DepartmentsRepository/PositionsRepository already
        # exposed: this is the "affectation" side of "compteur maintenu par
        # le service à chaque affectation ou départ."
        self._departments.increment_employee_count(request.department_id, delta=1)
        self._positions.increment_occupant_count(request.position_id, delta=1)

        increment_counter(self._db, _EMPLOYEES_ACTIVE_COUNTER, delta=1)
        if request.contract_type == ContractType.STAGE:
            increment_counter(self._db, _INTERNS_COUNTER, delta=1)

        self._notifications.notify_new_employee(employee)

        return employee

    def list(
        self,
        *,
        department_id: str | None = None,
        status: EmployeeStatus | None = None,
        contract_type: ContractType | None = None,
        search_prefix: str | None = None,
        cursor_id: str | None = None,
        limit: int = 25,
    ) -> list[EmployeeDocument]:
        return self._repository.list(
            department_id=department_id,
            status=status,
            contract_type=contract_type,
            search_prefix=search_prefix,
            cursor_id=cursor_id,
            limit=limit,
        )

    def get(self, employee_id: str) -> EmployeeDocument | None:
        return self._repository.get_by_id(employee_id)

    def decrypted_salary_and_rib(self, employee: EmployeeDocument) -> tuple[float, str]:
        return (
            float(crypto.decrypt(employee.gross_salary_encrypted)),
            crypto.decrypt(employee.rib_encrypted),
        )

    def update(
        self, employee_id: str, request: EmployeeUpdateRequest
    ) -> EmployeeDocument | None:
        existing = self._repository.get_by_id(employee_id)
        if existing is None:
            return None

        return self._repository.update(
            employee_id,
            first_name=request.first_name,
            last_name=request.last_name,
            cin=request.cin,
            birth_date=request.birth_date,
            professional_email=request.professional_email,
            phone=request.phone,
            hire_date=request.hire_date,
            contract_type=request.contract_type,
            contract_category=request.contract_category,
            contract_start_date=request.contract_start_date,
            contract_end_date=request.contract_end_date,
            gross_salary_encrypted=crypto.encrypt(str(request.gross_salary)),
            rib_encrypted=crypto.encrypt(request.rib),
            cnss_number=request.cnss_number,
            emergency_contact_name=request.emergency_contact_name,
            emergency_contact_phone=request.emergency_contact_phone,
            internal_notes=request.internal_notes,
        )

    def deactivate(self, employee_id: str) -> EmployeeDocument | None:
        employee = self._repository.get_by_id(employee_id)
        if employee is None:
            return None
        if employee.status == EmployeeStatus.INACTIVE:
            return employee  # idempotent: no double-decrement

        updated = self._repository.set_status(employee_id, EmployeeStatus.INACTIVE)
        self._departments.increment_employee_count(employee.department_id, delta=-1)
        self._positions.increment_occupant_count(employee.position_id, delta=-1)
        increment_counter(self._db, _EMPLOYEES_ACTIVE_COUNTER, delta=-1)
        if employee.contract_type == ContractType.STAGE:
            increment_counter(self._db, _INTERNS_COUNTER, delta=-1)
        return updated

    def activate(self, employee_id: str) -> EmployeeDocument | None:
        employee = self._repository.get_by_id(employee_id)
        if employee is None:
            return None
        if employee.status != EmployeeStatus.INACTIVE:
            return employee  # only a reactivation from INACTIVE counts as "départ" reversed

        updated = self._repository.set_status(employee_id, EmployeeStatus.ACTIVE)
        self._departments.increment_employee_count(employee.department_id, delta=1)
        self._positions.increment_occupant_count(employee.position_id, delta=1)
        increment_counter(self._db, _EMPLOYEES_ACTIVE_COUNTER, delta=1)
        if employee.contract_type == ContractType.STAGE:
            increment_counter(self._db, _INTERNS_COUNTER, delta=1)
        return updated
