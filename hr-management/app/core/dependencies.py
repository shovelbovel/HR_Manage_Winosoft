from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from google.cloud import firestore

from app.core import security
from app.core.ai_client import AIClient
from app.core.config import Settings, get_settings
from app.core.firestore_client import get_firestore_client
from app.models import CurrentUser, UserRole
from app.repositories.ai_audit_log_repository import AIAuditLogRepository
from app.repositories.certificates_repository import CertificatesRepository
from app.repositories.departments_repository import DepartmentsRepository
from app.repositories.employees_repository import EmployeesRepository
from app.repositories.holidays_repository import HolidaysRepository
from app.repositories.leave_balances_repository import LeaveBalancesRepository
from app.repositories.leave_types_repository import LeaveTypesRepository
from app.repositories.leaves_repository import LeavesRepository
from app.repositories.notifications_repository import NotificationsRepository
from app.repositories.positions_repository import PositionsRepository
from app.repositories.settings_repository import SettingsRepository
from app.repositories.trial_periods_repository import TrialPeriodsRepository
from app.repositories.users_repository import UsersRepository
from app.services.ai_service import AIService
from app.services.auth_service import AuthService
from app.services.certificates_service import CertificatesService
from app.services.dashboard_service import DashboardService
from app.services.departments_service import DepartmentsService
from app.services.employees_service import EmployeesService
from app.services.home_service import HomeService
from app.services.leaves_service import LeavesService
from app.services.notifications_service import NotificationsService
from app.services.positions_service import PositionsService
from app.services.settings_service import SettingsService
from app.services.trial_periods_service import TrialPeriodsService


def get_settings_dependency() -> Settings:
    return get_settings()


def get_db() -> firestore.Client:
    return get_firestore_client()


def get_users_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> UsersRepository:
    return UsersRepository(db)


def get_auth_service(
    users_repository: Annotated[UsersRepository, Depends(get_users_repository)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> AuthService:
    return AuthService(users_repository, settings)


def get_notifications_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> NotificationsRepository:
    return NotificationsRepository(db)


def get_notifications_service(
    notifications_repository: Annotated[
        NotificationsRepository, Depends(get_notifications_repository)
    ],
    users_repository: Annotated[UsersRepository, Depends(get_users_repository)],
) -> NotificationsService:
    return NotificationsService(notifications_repository, users_repository)


def get_departments_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> DepartmentsRepository:
    return DepartmentsRepository(db)


def get_departments_service(
    departments_repository: Annotated[DepartmentsRepository, Depends(get_departments_repository)],
) -> DepartmentsService:
    return DepartmentsService(departments_repository)


def get_positions_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> PositionsRepository:
    return PositionsRepository(db)


def get_positions_service(
    positions_repository: Annotated[PositionsRepository, Depends(get_positions_repository)],
    departments_repository: Annotated[DepartmentsRepository, Depends(get_departments_repository)],
) -> PositionsService:
    return PositionsService(positions_repository, departments_repository)


def get_employees_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> EmployeesRepository:
    return EmployeesRepository(db)


def get_trial_periods_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> TrialPeriodsRepository:
    return TrialPeriodsRepository(db)


def get_trial_periods_service(
    trial_periods_repository: Annotated[
        TrialPeriodsRepository, Depends(get_trial_periods_repository)
    ],
    employees_repository: Annotated[EmployeesRepository, Depends(get_employees_repository)],
) -> TrialPeriodsService:
    return TrialPeriodsService(trial_periods_repository, employees_repository)


def get_employees_service(
    db: Annotated[firestore.Client, Depends(get_db)],
    employees_repository: Annotated[EmployeesRepository, Depends(get_employees_repository)],
    departments_repository: Annotated[DepartmentsRepository, Depends(get_departments_repository)],
    positions_repository: Annotated[PositionsRepository, Depends(get_positions_repository)],
    trial_periods_service: Annotated[TrialPeriodsService, Depends(get_trial_periods_service)],
    notifications_service: Annotated[NotificationsService, Depends(get_notifications_service)],
) -> EmployeesService:
    return EmployeesService(
        db,
        employees_repository,
        departments_repository,
        positions_repository,
        trial_periods_service,
        notifications_service,
    )


def get_leave_types_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> LeaveTypesRepository:
    return LeaveTypesRepository(db)


def get_holidays_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> HolidaysRepository:
    return HolidaysRepository(db)


def get_leave_balances_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> LeaveBalancesRepository:
    return LeaveBalancesRepository(db)


def get_leaves_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> LeavesRepository:
    return LeavesRepository(db)


def get_leaves_service(
    db: Annotated[firestore.Client, Depends(get_db)],
    leaves_repository: Annotated[LeavesRepository, Depends(get_leaves_repository)],
    leave_balances_repository: Annotated[
        LeaveBalancesRepository, Depends(get_leave_balances_repository)
    ],
    leave_types_repository: Annotated[LeaveTypesRepository, Depends(get_leave_types_repository)],
    holidays_repository: Annotated[HolidaysRepository, Depends(get_holidays_repository)],
    employees_repository: Annotated[EmployeesRepository, Depends(get_employees_repository)],
    notifications_service: Annotated[NotificationsService, Depends(get_notifications_service)],
) -> LeavesService:
    return LeavesService(
        db,
        leaves_repository,
        leave_balances_repository,
        leave_types_repository,
        holidays_repository,
        employees_repository,
        notifications_service,
    )


def get_dashboard_service(
    db: Annotated[firestore.Client, Depends(get_db)],
    employees_repository: Annotated[EmployeesRepository, Depends(get_employees_repository)],
    departments_repository: Annotated[DepartmentsRepository, Depends(get_departments_repository)],
    leaves_service: Annotated[LeavesService, Depends(get_leaves_service)],
    trial_periods_service: Annotated[TrialPeriodsService, Depends(get_trial_periods_service)],
) -> DashboardService:
    return DashboardService(
        db, employees_repository, departments_repository, leaves_service, trial_periods_service
    )


def get_home_service(
    leaves_service: Annotated[LeavesService, Depends(get_leaves_service)],
    leave_types_repository: Annotated[LeaveTypesRepository, Depends(get_leave_types_repository)],
) -> HomeService:
    return HomeService(leaves_service, leave_types_repository)


def get_settings_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> SettingsRepository:
    return SettingsRepository(db)


def get_settings_service(
    settings_repository: Annotated[SettingsRepository, Depends(get_settings_repository)],
    leave_types_repository: Annotated[LeaveTypesRepository, Depends(get_leave_types_repository)],
    holidays_repository: Annotated[HolidaysRepository, Depends(get_holidays_repository)],
    users_repository: Annotated[UsersRepository, Depends(get_users_repository)],
    employees_repository: Annotated[EmployeesRepository, Depends(get_employees_repository)],
) -> SettingsService:
    return SettingsService(
        settings_repository,
        leave_types_repository,
        holidays_repository,
        users_repository,
        employees_repository,
    )


def get_certificates_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> CertificatesRepository:
    return CertificatesRepository(db)


def get_certificates_service(
    certificates_repository: Annotated[
        CertificatesRepository, Depends(get_certificates_repository)
    ],
    employees_repository: Annotated[EmployeesRepository, Depends(get_employees_repository)],
    leaves_repository: Annotated[LeavesRepository, Depends(get_leaves_repository)],
    settings_repository: Annotated[SettingsRepository, Depends(get_settings_repository)],
) -> CertificatesService:
    return CertificatesService(
        certificates_repository, employees_repository, leaves_repository, settings_repository
    )


def get_ai_client(
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> AIClient:
    return AIClient(settings.anthropic_api_key, settings.anthropic_model)


def get_ai_audit_log_repository(
    db: Annotated[firestore.Client, Depends(get_db)],
) -> AIAuditLogRepository:
    return AIAuditLogRepository(db)


def get_ai_service(
    db: Annotated[firestore.Client, Depends(get_db)],
    ai_client: Annotated[AIClient, Depends(get_ai_client)],
    ai_audit_log_repository: Annotated[AIAuditLogRepository, Depends(get_ai_audit_log_repository)],
    settings_repository: Annotated[SettingsRepository, Depends(get_settings_repository)],
    departments_repository: Annotated[DepartmentsRepository, Depends(get_departments_repository)],
    positions_repository: Annotated[PositionsRepository, Depends(get_positions_repository)],
) -> AIService:
    return AIService(
        ai_client,
        ai_audit_log_repository,
        settings_repository,
        departments_repository,
        positions_repository,
        db,
    )


def get_token_from_request(request: Request, settings: Settings) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:]
    return request.cookies.get(settings.cookie_name)


def get_current_user(
    request: Request,
    users_repository: Annotated[UsersRepository, Depends(get_users_repository)],
    settings: Annotated[Settings, Depends(get_settings_dependency)],
) -> CurrentUser:
    token = get_token_from_request(request, settings)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = security.decode_token(token, expected_type="access", settings=settings)
    except security.TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        ) from exc

    # Re-fetch from Firestore and re-check is_active on every request: this
    # is what makes deactivating a user take effect immediately rather than
    # at token expiry, per the cahier des charges' "Révocation" rule.
    user = users_repository.get_by_id(payload.sub)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    return CurrentUser(
        id=user.id,
        email=user.email,
        role=user.role,
        employee_id=user.employee_id,
        department_id=user.department_id,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(*roles: UserRole):
    """Dependency factory: 403s if the caller isn't one of `roles`.

    This guards "are you logged in with the right role at all." It is a
    different concern from the cahier des charges' "404 not 403" rule, which
    is about per-resource scope cloisonnement (e.g. a manager reading an
    employee outside their department) — that check belongs in the
    service/repository query logic of the module owning the resource, not
    here.
    """

    def _check(current_user: CurrentUserDep) -> CurrentUser:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return current_user

    return _check
