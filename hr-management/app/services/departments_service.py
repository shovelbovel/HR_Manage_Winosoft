from __future__ import annotations

from app.models import DepartmentDocument
from app.repositories.departments_repository import DepartmentsRepository


class DepartmentNotFoundError(Exception):
    """Raised when another module (Positions, Employees) references a
    department_id that doesn't exist. Maps to HTTP 404/400 in the caller's
    router — shared here since "does this department exist" is a
    Départements concern regardless of who's asking."""

    def __init__(self, department_id: str):
        self.department_id = department_id
        super().__init__(f"Department {department_id} does not exist")


class DepartmentNotEmptyError(Exception):
    """Raised when deletion is attempted on a department that still has
    employees. Maps to HTTP 409 in the router — see cahier des charges
    Module 4: "un département ne peut pas être supprimé s'il contient des
    employés actifs."""

    def __init__(self, department_id: str, employee_count: int):
        self.department_id = department_id
        self.employee_count = employee_count
        super().__init__(f"Department {department_id} still has {employee_count} employee(s)")


class DepartmentsService:
    def __init__(self, repository: DepartmentsRepository):
        self._repository = repository

    def create(self, code: str, name: str) -> DepartmentDocument:
        # AlreadyExistsError (repositories/base.py) bubbles up unchanged for
        # the router to translate to a 409 — same mechanism already used for
        # duplicate user emails, no new exception type needed for this.
        return self._repository.create(code=code, name=name)

    def list(self, cursor_id: str | None, limit: int = 25) -> list[DepartmentDocument]:
        return self._repository.list(cursor_id, limit)

    def get(self, department_id: str) -> DepartmentDocument | None:
        return self._repository.get_by_id(department_id)

    def rename(self, department_id: str, name: str) -> DepartmentDocument:
        # Deferred: the cahier des charges requires renaming to propagate the
        # denormalized department_name onto affected employee documents.
        # That propagation cannot be implemented until Module 3's
        # EmployeesRepository exists — this is the extension point for it.
        return self._repository.rename(department_id, name)

    def delete(self, department_id: str) -> DepartmentDocument | None:
        department = self._repository.get_by_id(department_id)
        if department is None:
            return None
        if department.employee_count > 0:
            raise DepartmentNotEmptyError(department_id, department.employee_count)
        self._repository.delete(department_id)
        return department
