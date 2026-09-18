from __future__ import annotations

from datetime import date, datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models import LeaveDocument, LeaveStatus
from app.repositories.base import date_to_utc_datetime, paginate

_COLLECTION = "leaves"


def _to_document(snapshot: firestore.DocumentSnapshot) -> LeaveDocument:
    data = snapshot.to_dict() or {}
    return LeaveDocument(id=snapshot.id, **data)


class LeavesRepository:
    """Data access only for the `leaves` collection — no business
    decisions. The approve workflow's cross-collection transaction is
    orchestrated by app.services.leaves_service, which is why this
    repository exposes read/write halves (`read_within_transaction`/
    `apply_approval_within_transaction`) instead of a single self-contained
    transactional method — the transaction has to span this collection
    *and* leave_balances.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def get_by_id(self, leave_id: str) -> LeaveDocument | None:
        snapshot = self._collection.document(leave_id).get()
        return _to_document(snapshot) if snapshot.exists else None

    def list(
        self,
        *,
        employee_id: str | None = None,
        department_id: str | None = None,
        status: LeaveStatus | None = None,
        cursor_id: str | None = None,
        limit: int = 25,
    ) -> list[LeaveDocument]:
        # Scope boundary matched by firestore.indexes.json, same as
        # EmployeesRepository.list: at most one of employee_id/department_id
        # is expected combined with status at a time.
        query = self._collection
        if employee_id:
            query = query.where(filter=FieldFilter("employee_id", "==", employee_id))
        if department_id:
            query = query.where(filter=FieldFilter("department_id", "==", department_id))
        if status:
            query = query.where(filter=FieldFilter("status", "==", status.value))
        query = query.order_by("requested_at", direction=firestore.Query.DESCENDING)
        cursor_snapshot = self._collection.document(cursor_id).get() if cursor_id else None
        query = paginate(query, cursor_snapshot, limit)
        return [_to_document(snapshot) for snapshot in query.stream()]

    def list_approved_for_employee(self, employee_id: str) -> list[LeaveDocument]:
        query = self._collection.where(
            filter=FieldFilter("employee_id", "==", employee_id)
        ).where(filter=FieldFilter("status", "==", LeaveStatus.APPROVED.value))
        return [_to_document(snapshot) for snapshot in query.stream()]

    def create(
        self,
        *,
        employee_id: str,
        employee_name: str,
        department_id: str,
        leave_type_id: str,
        leave_type_name: str,
        start_date: date,
        end_date: date,
        working_days: int,
        reason: str | None,
    ) -> LeaveDocument:
        doc_ref = self._collection.document()
        now = datetime.now(timezone.utc)
        data = {
            "employee_id": employee_id,
            "employee_name": employee_name,
            "department_id": department_id,
            "leave_type_id": leave_type_id,
            "leave_type_name": leave_type_name,
            "start_date": date_to_utc_datetime(start_date),
            "end_date": date_to_utc_datetime(end_date),
            "working_days": working_days,
            "status": LeaveStatus.PENDING.value,
            "reason": reason,
            "rejection_reason": None,
            "requested_at": now,
            "decided_at": None,
            "decided_by": None,
            "created_at": now,
            "updated_at": now,
        }
        doc_ref.set(data)
        return _to_document(doc_ref.get())

    def reject(self, leave_id: str, *, reason: str, decided_by: str) -> LeaveDocument:
        doc_ref = self._collection.document(leave_id)
        now = datetime.now(timezone.utc)
        doc_ref.update(
            {
                "status": LeaveStatus.REJECTED.value,
                "rejection_reason": reason,
                "decided_at": now,
                "decided_by": decided_by,
                "updated_at": now,
            }
        )
        return _to_document(doc_ref.get())

    def read_within_transaction(
        self, transaction: firestore.Transaction, leave_id: str
    ) -> tuple[firestore.DocumentReference, firestore.DocumentSnapshot]:
        doc_ref = self._collection.document(leave_id)
        return doc_ref, doc_ref.get(transaction=transaction)

    def apply_approval_within_transaction(
        self,
        transaction: firestore.Transaction,
        doc_ref: firestore.DocumentReference,
        *,
        decided_by: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        transaction.update(
            doc_ref,
            {
                "status": LeaveStatus.APPROVED.value,
                "decided_at": now,
                "decided_by": decided_by,
                "updated_at": now,
            },
        )
