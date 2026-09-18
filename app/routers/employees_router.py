from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.dependencies import (
    CurrentUserDep,
    get_departments_service,
    get_employees_service,
    get_leaves_service,
    get_positions_service,
    require_role,
)
from app.core.http import flash_redirect, read_body, wants_json
from app.core.templating import templates
from app.models import (
    ContractType,
    EmployeeCreateRequest,
    EmployeeStatus,
    EmployeeUpdateRequest,
    UserRole,
)
from app.repositories.base import AlreadyExistsError
from app.services import attrition_service
from app.services.departments_service import DepartmentNotFoundError, DepartmentsService
from app.services.employees_service import (
    EmployeesService,
    PositionCapacityExceededError,
    PositionDepartmentMismatchError,
)
from app.services.leaves_service import LeavesService
from app.services.positions_service import PositionNotFoundError, PositionsService

router = APIRouter(
    prefix="/employees",
    tags=["employees"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)

_PAGE_SIZE_DEFAULT = 25
_ALLOWED_PAGE_SIZES = (10, 25, 50)
_PICKER_LIMIT = 200

_CSV_COLUMNS = [
    "matricule",
    "first_name",
    "last_name",
    "cin",
    "professional_email",
    "phone",
    "department_name",
    "position_title",
    "hire_date",
    "contract_type",
    "contract_start_date",
    "contract_end_date",
    "status",
    "cnss_number",
]


def _picker_context(
    departments_service: DepartmentsService, positions_service: PositionsService
) -> dict:
    return {
        "departments": departments_service.list(cursor_id=None, limit=_PICKER_LIMIT),
        "positions": positions_service.list(department_id=None, cursor_id=None, limit=_PICKER_LIMIT),
    }


@router.get("/export")
def export_employees_csv(
    service: Annotated[EmployeesService, Depends(get_employees_service)],
    department_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[EmployeeStatus | None, Query(alias="status")] = None,
    contract_type: Annotated[ContractType | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
):
    # Registered before GET /{employee_id} — see routing-order note in the
    # implementation plan. Salary and RIB are deliberately excluded (cahier
    # des charges: "un export circule par messagerie et échappe au
    # chiffrement au repos"), everything else in the filtered list is kept.
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()

    cursor_id: str | None = None
    while True:
        page = service.list(
            department_id=department_id,
            status=status_filter,
            contract_type=contract_type,
            search_prefix=search,
            cursor_id=cursor_id,
            limit=50,
        )
        if not page:
            break
        for employee in page:
            # model_dump(mode="json") serializes the ContractType/EmployeeStatus
            # enums to their .value automatically; gross_salary_encrypted and
            # rib_encrypted end up in this dict too but DictWriter's
            # extrasaction="ignore" (fieldnames=_CSV_COLUMNS) drops them.
            writer.writerow(employee.model_dump(mode="json"))
        if len(page) < 50:
            break
        cursor_id = page[-1].id

    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=employees.csv"},
    )


@router.get("")
def list_employees(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[EmployeesService, Depends(get_employees_service)],
    departments_service: Annotated[DepartmentsService, Depends(get_departments_service)],
    department_id: Annotated[str | None, Query()] = None,
    status_filter: Annotated[EmployeeStatus | None, Query(alias="status")] = None,
    contract_type: Annotated[ContractType | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = _PAGE_SIZE_DEFAULT,
):
    page_size = limit if limit in _ALLOWED_PAGE_SIZES else _PAGE_SIZE_DEFAULT
    employees = service.list(
        department_id=department_id,
        status=status_filter,
        contract_type=contract_type,
        search_prefix=search,
        cursor_id=cursor,
        limit=page_size,
    )
    if wants_json(request):
        return employees

    next_cursor = employees[-1].id if len(employees) == page_size else None
    return templates.TemplateResponse(
        request,
        "employees/list.html",
        {
            "current_user": current_user,
            "employees": employees,
            "next_cursor": next_cursor,
            "departments": departments_service.list(cursor_id=None, limit=_PICKER_LIMIT),
            "filters": {
                "department_id": department_id or "",
                "status": status_filter.value if status_filter else "",
                "contract_type": contract_type.value if contract_type else "",
                "search": search or "",
                "limit": page_size,
            },
            "error": None,
        },
    )


@router.get("/create")
def create_employee_page(
    request: Request,
    current_user: CurrentUserDep,
    departments_service: Annotated[DepartmentsService, Depends(get_departments_service)],
    positions_service: Annotated[PositionsService, Depends(get_positions_service)],
    first_name: Annotated[str | None, Query()] = None,
    last_name: Annotated[str | None, Query()] = None,
    professional_email: Annotated[str | None, Query()] = None,
    phone: Annotated[str | None, Query()] = None,
    birth_date: Annotated[str | None, Query()] = None,
    summary: Annotated[str | None, Query()] = None,
    suggested_department_id: Annotated[str | None, Query()] = None,
    suggested_position_id: Annotated[str | None, Query()] = None,
    skills: Annotated[str | None, Query()] = None,
    suggested_contract_type: Annotated[str | None, Query()] = None,
):
    # Optional query params: Module 12's CV import redirects here with
    # extracted values pre-filled, flagged in the template as AI-provided
    # (employees/form.html shows an "IA" badge when `prefill` is present).
    # This is a UI convenience only — nothing is ever created from these
    # params directly, the admin still reviews and submits the form.
    # `skills` arrives comma-joined (the redirect just stringifies the
    # JSON array's list value) — split it back out for the template.
    prefill = {
        "first_name": first_name,
        "last_name": last_name,
        "professional_email": professional_email,
        "phone": phone,
        "birth_date": birth_date,
        "summary": summary,
        "suggested_department_id": suggested_department_id,
        "suggested_position_id": suggested_position_id,
        "skills": skills.split(",") if skills else None,
        "suggested_contract_type": suggested_contract_type,
    }
    has_prefill = any(prefill.values())
    return templates.TemplateResponse(
        request,
        "employees/form.html",
        {
            "current_user": current_user,
            "employee": None,
            "error": None,
            "prefill": prefill if has_prefill else None,
            **_picker_context(departments_service, positions_service),
        },
    )


@router.post("")
async def create_employee(
    request: Request,
    current_user: CurrentUserDep,
    service: Annotated[EmployeesService, Depends(get_employees_service)],
    departments_service: Annotated[DepartmentsService, Depends(get_departments_service)],
    positions_service: Annotated[PositionsService, Depends(get_positions_service)],
):
    json_wanted = wants_json(request)
    payload = await read_body(request, EmployeeCreateRequest)

    try:
        employee = service.create(payload)
    except (
        DepartmentNotFoundError,
        PositionNotFoundError,
        PositionDepartmentMismatchError,
        PositionCapacityExceededError,
        AlreadyExistsError,
    ) as exc:
        error = _create_error_message(exc)
        not_found_errors = (
            DepartmentNotFoundError,
            PositionNotFoundError,
            PositionDepartmentMismatchError,
        )
        status_code = (
            status.HTTP_400_BAD_REQUEST
            if isinstance(exc, not_found_errors)
            else status.HTTP_409_CONFLICT
        )
        if json_wanted:
            raise HTTPException(status_code=status_code, detail=error) from exc
        return templates.TemplateResponse(
            request,
            "employees/form.html",
            {
                "current_user": current_user,
                "employee": None,
                "error": error,
                **_picker_context(departments_service, positions_service),
            },
            status_code=status_code,
        )

    if json_wanted:
        return employee
    return RedirectResponse(f"/employees/{employee.id}", status_code=status.HTTP_303_SEE_OTHER)


_DUPLICATE_FIELD_LABELS = {
    "matricule": "Ce matricule",
    "cin": "Ce CIN",
    "professional_email": "Cet email professionnel",
}


def _create_error_message(exc: Exception) -> str:
    if isinstance(exc, DepartmentNotFoundError):
        return "Le département sélectionné n'existe pas."
    if isinstance(exc, PositionNotFoundError):
        return "Le poste sélectionné n'existe pas."
    if isinstance(exc, PositionDepartmentMismatchError):
        return "Ce poste n'appartient pas au département sélectionné."
    if isinstance(exc, PositionCapacityExceededError):
        return f"Ce poste a atteint sa capacité maximale ({exc.max_occupants})."
    if isinstance(exc, AlreadyExistsError):
        label = _DUPLICATE_FIELD_LABELS.get(exc.field, f"La valeur « {exc.field} »")
        return f"{label} est déjà utilisé(e)."
    return "Requête invalide."


@router.get("/{employee_id}")
def employee_detail(
    request: Request,
    employee_id: str,
    current_user: CurrentUserDep,
    service: Annotated[EmployeesService, Depends(get_employees_service)],
    leaves_service: Annotated[LeavesService, Depends(get_leaves_service)],
):
    employee = service.get(employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return employee

    # Whole module is admin-only today, so this is trivially true — but the
    # field-level gate is coded explicitly (not just "the route is
    # admin-only") so it stays correct once Manager access to a read-only
    # employee view is added in a later module, per the cahier des charges'
    # "le salaire n'est transmis au gabarit que pour un administrateur" rule.
    gross_salary, rib = service.decrypted_salary_and_rib(employee)
    # Local model, never sent to any external provider — see
    # app/services/attrition_service.py's module docstring for why that
    # makes this a different privacy situation than the AI assistant.
    attrition_risk = attrition_service.score_employee(employee, gross_salary)
    recent_leaves, leave_balances = leaves_service.summary_for_employee(employee_id)
    leave_type_names = {lt.id: lt.name for lt in leaves_service.list_leave_types()}

    return templates.TemplateResponse(
        request,
        "employees/detail.html",
        {
            "current_user": current_user,
            "employee": employee,
            "attrition_risk": attrition_risk,
            "gross_salary": gross_salary,
            "rib": rib,
            "recent_leaves": recent_leaves,
            "leave_balances": leave_balances,
            "leave_type_names": leave_type_names,
            "error": None,
        },
    )


@router.post("/{employee_id}")
async def update_employee(
    request: Request,
    employee_id: str,
    service: Annotated[EmployeesService, Depends(get_employees_service)],
):
    payload = await read_body(request, EmployeeUpdateRequest)
    updated = service.update(employee_id, payload)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if wants_json(request):
        return updated
    return RedirectResponse(f"/employees/{employee_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{employee_id}/deactivate")
def deactivate_employee(
    request: Request,
    employee_id: str,
    service: Annotated[EmployeesService, Depends(get_employees_service)],
):
    updated = service.deactivate(employee_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if wants_json(request):
        return updated
    return flash_redirect(f"/employees/{employee_id}", "Employé désactivé.", "success")


@router.post("/{employee_id}/activate")
def activate_employee(
    request: Request,
    employee_id: str,
    service: Annotated[EmployeesService, Depends(get_employees_service)],
):
    updated = service.activate(employee_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if wants_json(request):
        return updated
    return flash_redirect(f"/employees/{employee_id}", "Employé réactivé.", "success")
