from __future__ import annotations

from app.core import security
from app.core.config import Settings, get_settings
from app.models import (
    AISettings,
    AISettingsUpdateRequest,
    CompanySettings,
    CompanySettingsUpdateRequest,
    HolidayCreateRequest,
    HolidayDocument,
    LeaveTypeCreateRequest,
    LeaveTypeDocument,
    LeaveTypeUpdateRequest,
    UserCreateRequest,
    UserDocument,
    UserPasswordResetRequest,
)
from app.repositories.employees_repository import EmployeesRepository
from app.repositories.holidays_repository import HolidaysRepository
from app.repositories.leave_types_repository import LeaveTypesRepository
from app.repositories.settings_repository import SettingsRepository
from app.repositories.users_repository import UsersRepository


class EmployeeNotFoundError(Exception):
    def __init__(self, employee_id: str):
        self.employee_id = employee_id
        super().__init__(f"Employee {employee_id} does not exist")


class SettingsService:
    """Aggregation point for every /settings/* screen (Module 11) — one
    admin-only surface, several config domains, matching the cahier des
    charges' own framing of the module. get/set company info has no
    business rule beyond "admin only" (already enforced at the router);
    the leave-types/holidays/users methods carry real rules (uniqueness,
    role-specific requirements, password policy).
    """

    def __init__(
        self,
        settings_repository: SettingsRepository,
        leave_types_repository: LeaveTypesRepository,
        holidays_repository: HolidaysRepository,
        users_repository: UsersRepository,
        employees_repository: EmployeesRepository,
        settings: Settings | None = None,
    ):
        self._settings_repo = settings_repository
        self._leave_types = leave_types_repository
        self._holidays = holidays_repository
        self._users = users_repository
        self._employees = employees_repository
        self._settings = settings or get_settings()

    # -- Entreprise -----------------------------------------------------

    def get_company(self) -> CompanySettings | None:
        return self._settings_repo.get_company()

    def set_company(self, request: CompanySettingsUpdateRequest) -> CompanySettings:
        return self._settings_repo.set_company(
            name=request.name,
            address=request.address,
            ice=request.ice,
            rc=request.rc,
            if_number=request.if_number,
        )

    # -- Congés -----------------------------------------------------------

    def list_leave_types(self) -> list[LeaveTypeDocument]:
        return self._leave_types.list()

    def create_leave_type(self, request: LeaveTypeCreateRequest) -> LeaveTypeDocument:
        # AlreadyExistsError (repositories/base.py) bubbles up unchanged
        # for the router to translate to a 409 — same mechanism as
        # duplicate department codes/user emails.
        return self._leave_types.create(
            code=request.code,
            name=request.name,
            default_days_per_year=request.default_days_per_year,
            is_deductible=request.is_deductible,
            requires_justification=request.requires_justification,
        )

    def update_leave_type(
        self, leave_type_id: str, request: LeaveTypeUpdateRequest
    ) -> LeaveTypeDocument | None:
        if self._leave_types.get_by_id(leave_type_id) is None:
            return None
        return self._leave_types.update(
            leave_type_id,
            name=request.name,
            default_days_per_year=request.default_days_per_year,
            is_deductible=request.is_deductible,
            requires_justification=request.requires_justification,
        )

    def list_holidays(self) -> list[HolidayDocument]:
        return self._holidays.list()

    def create_holiday(self, request: HolidayCreateRequest) -> HolidayDocument:
        return self._holidays.create(
            name=request.name,
            is_recurring=request.is_recurring,
            month=request.month,
            day=request.day,
            year=request.year,
        )

    def delete_holiday(self, holiday_id: str) -> None:
        self._holidays.delete(holiday_id)

    # -- Utilisateurs -----------------------------------------------------

    def list_users(self, cursor_id: str | None = None, limit: int = 25) -> list[UserDocument]:
        return self._users.list(cursor_id=cursor_id, limit=limit)

    def get_user(self, user_id: str) -> UserDocument | None:
        return self._users.get_by_id(user_id)

    def create_user(self, request: UserCreateRequest) -> UserDocument:
        if request.employee_id is not None:
            if self._employees.get_by_id(request.employee_id) is None:
                raise EmployeeNotFoundError(request.employee_id)
        hashed_password = security.hash_password(request.password, settings=self._settings)
        return self._users.create(
            email=request.email,
            hashed_password=hashed_password,
            role=request.role,
            employee_id=request.employee_id,
            department_id=request.department_id,
        )

    def reset_user_password(
        self, user_id: str, request: UserPasswordResetRequest
    ) -> UserDocument | None:
        if self._users.get_by_id(user_id) is None:
            return None
        hashed_password = security.hash_password(request.password, settings=self._settings)
        self._users.set_password(user_id, hashed_password)
        return self._users.get_by_id(user_id)

    def activate_user(self, user_id: str) -> UserDocument | None:
        if self._users.get_by_id(user_id) is None:
            return None
        self._users.set_active(user_id, True)
        return self._users.get_by_id(user_id)

    def deactivate_user(self, user_id: str) -> UserDocument | None:
        if self._users.get_by_id(user_id) is None:
            return None
        self._users.set_active(user_id, False)
        return self._users.get_by_id(user_id)

    # -- Assistant (Module 12) ---------------------------------------------

    def get_ai(self) -> AISettings | None:
        return self._settings_repo.get_ai()

    def set_ai(self, request: AISettingsUpdateRequest) -> AISettings:
        return self._settings_repo.set_ai(
            enabled=request.enabled,
            daily_quota_per_user=request.daily_quota_per_user,
            monthly_quota_global=request.monthly_quota_global,
        )
