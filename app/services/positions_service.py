from __future__ import annotations

from app.models import PositionDocument
from app.repositories.departments_repository import DepartmentsRepository
from app.repositories.positions_repository import PositionsRepository
from app.services.departments_service import DepartmentNotFoundError

__all__ = [
    "DepartmentNotFoundError",
    "PositionNotEmptyError",
    "PositionNotFoundError",
    "PositionsService",
]


class PositionNotFoundError(Exception):
    """Raised when another module (Employees) references a position_id that
    doesn't exist. Maps to 404/400 in the caller's router."""

    def __init__(self, position_id: str):
        self.position_id = position_id
        super().__init__(f"Position {position_id} does not exist")


class PositionNotEmptyError(Exception):
    """Raised when deletion is attempted on a position that still has
    occupants. Maps to HTTP 409 — cahier des charges Module 5: "un poste ne
    peut pas être supprimé s'il est occupé."""

    def __init__(self, position_id: str, occupant_count: int):
        self.position_id = position_id
        self.occupant_count = occupant_count
        super().__init__(f"Position {position_id} still has {occupant_count} occupant(s)")


class PositionsService:
    def __init__(
        self,
        repository: PositionsRepository,
        departments_repository: DepartmentsRepository,
    ):
        self._repository = repository
        self._departments = departments_repository

    def create(
        self, department_id: str, title: str, max_occupants: int | None
    ) -> PositionDocument:
        department = self._departments.get_by_id(department_id)
        if department is None:
            raise DepartmentNotFoundError(department_id)
        return self._repository.create(
            department_id=department_id,
            department_name=department.name,
            title=title,
            max_occupants=max_occupants,
        )

    def list(
        self, department_id: str | None, cursor_id: str | None, limit: int = 25
    ) -> list[PositionDocument]:
        return self._repository.list(department_id, cursor_id, limit)

    def get(self, position_id: str) -> PositionDocument | None:
        return self._repository.get_by_id(position_id)

    def update(
        self, position_id: str, title: str, max_occupants: int | None
    ) -> PositionDocument:
        return self._repository.update(position_id, title=title, max_occupants=max_occupants)

    def delete(self, position_id: str) -> PositionDocument | None:
        position = self._repository.get_by_id(position_id)
        if position is None:
            return None
        if position.occupant_count > 0:
            raise PositionNotEmptyError(position_id, position.occupant_count)
        self._repository.delete(position_id)
        return position
