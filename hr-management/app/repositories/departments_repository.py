from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore

from app.models import DepartmentDocument
from app.repositories.base import (
    acquire_unique_lock,
    get_unique_lock_owner,
    increment_counter,
    paginate,
    release_unique_lock,
)

_COLLECTION = "departments"
_CODE_FIELD = "code"
_ACTIVE_COUNTER = "departments_active"


def _to_document(snapshot: firestore.DocumentSnapshot) -> DepartmentDocument:
    data = snapshot.to_dict() or {}
    return DepartmentDocument(id=snapshot.id, **data)


class DepartmentsRepository:
    """Data access only for the `departments` collection — no business
    decisions. The "cannot delete while occupied" rule lives in
    app.services.departments_service, per the cahier des charges layering
    rule.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def get_by_id(self, department_id: str) -> DepartmentDocument | None:
        snapshot = self._collection.document(department_id).get()
        if not snapshot.exists:
            return None
        return _to_document(snapshot)

    def get_by_code(self, code: str) -> DepartmentDocument | None:
        department_id = get_unique_lock_owner(self._db, _CODE_FIELD, code)
        if department_id is None:
            return None
        return self.get_by_id(department_id)

    def list(self, cursor_id: str | None, limit: int = 25) -> list[DepartmentDocument]:
        query = self._collection.order_by("name")
        cursor_snapshot = self._collection.document(cursor_id).get() if cursor_id else None
        query = paginate(query, cursor_snapshot, limit)
        return [_to_document(snapshot) for snapshot in query.stream()]

    def create(self, *, code: str, name: str) -> DepartmentDocument:
        doc_ref = self._collection.document()
        acquire_unique_lock(self._db, _CODE_FIELD, code, owner_id=doc_ref.id)
        try:
            now = datetime.now(timezone.utc)
            data = {
                "code": code,
                "name": name,
                "employee_count": 0,
                "created_at": now,
                "updated_at": now,
            }
            doc_ref.set(data)
        except Exception:
            release_unique_lock(self._db, _CODE_FIELD, code)
            raise
        increment_counter(self._db, _ACTIVE_COUNTER, delta=1)
        return _to_document(doc_ref.get())

    def rename(self, department_id: str, name: str) -> DepartmentDocument:
        doc_ref = self._collection.document(department_id)
        doc_ref.update({"name": name, "updated_at": datetime.now(timezone.utc)})
        return _to_document(doc_ref.get())

    def delete(self, department_id: str) -> None:
        department = self.get_by_id(department_id)
        if department is None:
            return
        self._collection.document(department_id).delete()
        release_unique_lock(self._db, _CODE_FIELD, department.code)
        increment_counter(self._db, _ACTIVE_COUNTER, delta=-1)

    def increment_employee_count(self, department_id: str, delta: int = 1) -> int:
        """Per-entity counter on the department's own doc, distinct from the
        global _counters collection used for departments_active. Not called
        by anything yet — Module 3 (employees) will call this on
        create/deactivate once it exists.
        """
        doc_ref = self._collection.document(department_id)

        @firestore.transactional
        def _bump(transaction: firestore.Transaction) -> int:
            snapshot = doc_ref.get(transaction=transaction)
            current = (snapshot.to_dict() or {}).get("employee_count", 0)
            new_value = current + delta
            transaction.update(
                doc_ref,
                {"employee_count": new_value, "updated_at": datetime.now(timezone.utc)},
            )
            return new_value

        return _bump(self._db.transaction())
