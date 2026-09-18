from __future__ import annotations

from app.core import crypto
from app.core.exceptions import ResourceOutOfScopeError
from app.core.pdf import render_html_to_pdf
from app.core.templating import templates
from app.models import (
    CertificateDocument,
    CertificateGenerateRequest,
    CertificateType,
    CurrentUser,
    EmployeeDocument,
    LeaveStatus,
    UserRole,
)
from app.repositories.certificates_repository import CertificatesRepository
from app.repositories.employees_repository import EmployeesRepository
from app.repositories.leaves_repository import LeavesRepository
from app.repositories.settings_repository import SettingsRepository

_ADMIN_ONLY_TYPES = {CertificateType.SALARY, CertificateType.END_OF_CONTRACT}
_DATE_FORMAT = "%d/%m/%Y"


class EmployeeNotFoundError(Exception):
    def __init__(self, employee_id: str):
        self.employee_id = employee_id
        super().__init__(f"Employee {employee_id} does not exist")


class CertificateTypeNotAllowedError(Exception):
    """Raised when the caller's role can't generate this certificate type
    — Admin-only for SALARY/END_OF_CONTRACT, per the access matrix."""

    def __init__(self, certificate_type: CertificateType):
        self.certificate_type = certificate_type
        super().__init__(f"{certificate_type.value} is admin-only")


class LeaveNotEligibleError(Exception):
    """Raised when the referenced leave isn't APPROVED or doesn't belong
    to the target employee — a LEAVE certificate can only certify a
    confirmed absence."""

    def __init__(self, leave_id: str):
        self.leave_id = leave_id
        super().__init__(f"Leave {leave_id} is not an approved leave for this employee")


class NotAnInternError(Exception):
    """Raised when an INTERNSHIP certificate is requested for an employee
    whose contract_type isn't STAGE."""

    def __init__(self, employee_id: str):
        self.employee_id = employee_id
        super().__init__(f"Employee {employee_id} is not a STAGE contract")


class CertificatesService:
    def __init__(
        self,
        repository: CertificatesRepository,
        employees_repository: EmployeesRepository,
        leaves_repository: LeavesRepository,
        settings_repository: SettingsRepository,
    ):
        self._repository = repository
        self._employees = employees_repository
        self._leaves = leaves_repository
        self._settings = settings_repository

    def _check_employee_scope(self, current_user: CurrentUser, employee: EmployeeDocument) -> None:
        if current_user.role == UserRole.ADMIN:
            return
        if current_user.role == UserRole.MANAGER:
            if employee.department_id != current_user.department_id:
                raise ResourceOutOfScopeError()
            return
        if employee.id != current_user.employee_id:
            raise ResourceOutOfScopeError()

    def _company_snapshot(self) -> dict:
        company = self._settings.get_company()
        if company is None:
            return {"name": "", "address": "", "ice": "", "rc": "", "if_number": ""}
        return {
            "name": company.name,
            "address": company.address,
            "ice": company.ice,
            "rc": company.rc,
            "if_number": company.if_number,
        }

    def generate(
        self, current_user: CurrentUser, request: CertificateGenerateRequest
    ) -> CertificateDocument:
        if request.certificate_type in _ADMIN_ONLY_TYPES and current_user.role != UserRole.ADMIN:
            raise CertificateTypeNotAllowedError(request.certificate_type)

        employee = self._employees.get_by_id(request.employee_id)
        if employee is None:
            raise EmployeeNotFoundError(request.employee_id)
        self._check_employee_scope(current_user, employee)

        base = {
            "employee_name": f"{employee.first_name} {employee.last_name}",
            "matricule": employee.matricule,
            "department_name": employee.department_name,
            "position_title": employee.position_title,
            **self._company_snapshot(),
        }

        if request.certificate_type == CertificateType.WORK:
            snapshot = {**base, "hire_date": employee.hire_date.strftime(_DATE_FORMAT)}
        elif request.certificate_type == CertificateType.INTERNSHIP:
            if employee.contract_type.value != "STAGE":
                raise NotAnInternError(employee.id)
            end_date = (
                employee.contract_end_date.strftime(_DATE_FORMAT)
                if employee.contract_end_date
                else "en cours"
            )
            snapshot = {
                **base,
                "start_date": employee.contract_start_date.strftime(_DATE_FORMAT),
                "end_date": end_date,
                "subject": request.internship_subject,
            }
        elif request.certificate_type == CertificateType.LEAVE:
            leave = self._leaves.get_by_id(request.leave_id) if request.leave_id else None
            if (
                leave is None
                or leave.status != LeaveStatus.APPROVED
                or leave.employee_id != employee.id
            ):
                raise LeaveNotEligibleError(request.leave_id or "")
            snapshot = {
                **base,
                "leave_type_name": leave.leave_type_name,
                "start_date": leave.start_date.strftime(_DATE_FORMAT),
                "end_date": leave.end_date.strftime(_DATE_FORMAT),
                "working_days": leave.working_days,
            }
        elif request.certificate_type == CertificateType.SALARY:
            gross_salary = float(crypto.decrypt(employee.gross_salary_encrypted))
            snapshot = {
                **base,
                "gross_salary": gross_salary,
                "net_salary": request.net_salary,
            }
        else:  # END_OF_CONTRACT
            snapshot = {
                **base,
                "contract_type": employee.contract_type.value,
                "contract_category": (
                    employee.contract_category.value if employee.contract_category else None
                ),
                "hire_date": employee.hire_date.strftime(_DATE_FORMAT),
                "contract_start_date": employee.contract_start_date.strftime(_DATE_FORMAT),
                "contract_end_date": (
                    employee.contract_end_date.strftime(_DATE_FORMAT)
                    if employee.contract_end_date
                    else None
                ),
            }

        return self._repository.create(
            certificate_type=request.certificate_type,
            employee_id=employee.id,
            department_id=employee.department_id,
            generated_by=current_user.id,
            data_snapshot=snapshot,
        )

    def get(self, current_user: CurrentUser, certificate_id: str) -> CertificateDocument | None:
        certificate = self._repository.get_by_id(certificate_id)
        if certificate is None:
            return None
        if current_user.role == UserRole.ADMIN:
            return certificate
        if current_user.role == UserRole.MANAGER:
            if certificate.department_id != current_user.department_id:
                raise ResourceOutOfScopeError()
            return certificate
        if certificate.employee_id != current_user.employee_id:
            raise ResourceOutOfScopeError()
        return certificate

    def list_all(
        self, current_user: CurrentUser, cursor_id: str | None = None, limit: int = 25
    ) -> list[CertificateDocument]:
        if current_user.role == UserRole.ADMIN:
            return self._repository.list(cursor_id=cursor_id, limit=limit)
        return self._repository.list(
            department_id=current_user.department_id, cursor_id=cursor_id, limit=limit
        )

    def list_my(
        self, current_user: CurrentUser, cursor_id: str | None = None, limit: int = 25
    ) -> list[CertificateDocument]:
        if not current_user.employee_id:
            return []
        return self._repository.list(
            employee_id=current_user.employee_id, cursor_id=cursor_id, limit=limit
        )

    def render_pdf(self, certificate: CertificateDocument) -> bytes:
        template = templates.get_template(f"certificates/pdf/{certificate.certificate_type.value}.html")
        html = template.render(certificate=certificate, data=certificate.data_snapshot)
        return render_html_to_pdf(html)
