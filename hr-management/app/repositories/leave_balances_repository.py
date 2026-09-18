from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models import LeaveBalanceDocument

_COLLECTION = "leave_balances"


def _balance_id(employee_id: str, leave_type_id: str, year: int) -> str:
    # Replaces UNIQUE(employee_id, leave_type_id, year): a duplicate becomes
    # impossible by construction, per the cahier des charges.
    return f"{employee_id}_{leave_type_id}_{year}"


def _to_document(snapshot: firestore.DocumentSnapshot) -> LeaveBalanceDocument:
    data = snapshot.to_dict() or {}
    return LeaveBalanceDocument(id=snapshot.id, **data)


class LeaveBalancesRepository:
    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def _doc_ref(
        self, employee_id: str, leave_type_id: str, year: int
    ) -> firestore.DocumentReference:
        return self._collection.document(_balance_id(employee_id, leave_type_id, year))

    def get(self, employee_id: str, leave_type_id: str, year: int) -> LeaveBalanceDocument | None:
        snapshot = self._doc_ref(employee_id, leave_type_id, year).get()
        return _to_document(snapshot) if snapshot.exists else None

    def get_or_create(
        self, employee_id: str, leave_type_id: str, year: int, default_initial: int
    ) -> LeaveBalanceDocument:
        """Plain (non-transactional) convenience for read paths outside the
        approve workflow — e.g. checking remaining balance at submission
        time, or the balances list view.
        """
        doc_ref = self._doc_ref(employee_id, leave_type_id, year)
        snapshot = doc_ref.get()
        if snapshot.exists:
            return _to_document(snapshot)
        now = datetime.now(timezone.utc)
        data = {
            "employee_id": employee_id,
            "leave_type_id": leave_type_id,
            "year": year,
            "initial": default_initial,
            "accrued": 0,
            "used": 0,
            "created_at": now,
            "updated_at": now,
        }
        doc_ref.set(data)
        return _to_document(doc_ref.get())

    def list_for_employee(self, employee_id: str) -> list[LeaveBalanceDocument]:
        query = self._collection.where(filter=FieldFilter("employee_id", "==", employee_id))
        return [_to_document(snapshot) for snapshot in query.stream()]

    def list_all(self) -> list[LeaveBalanceDocument]:
        return [_to_document(snapshot) for snapshot in self._collection.stream()]

    def read_within_transaction(
        self, transaction: firestore.Transaction, employee_id: str, leave_type_id: str, year: int
    ) -> tuple[firestore.DocumentReference, firestore.DocumentSnapshot]:
        """The READ half of the approve workflow's balance update — must be
        called before any write in the same transaction (Firestore forbids
        reads after the first write in a transaction).
        """
        doc_ref = self._doc_ref(employee_id, leave_type_id, year)
        return doc_ref, doc_ref.get(transaction=transaction)

    def apply_usage_within_transaction(
        self,
        transaction: firestore.Transaction,
        doc_ref: firestore.DocumentReference,
        snapshot: firestore.DocumentSnapshot,
        *,
        employee_id: str,
        leave_type_id: str,
        year: int,
        default_initial: int,
        delta_used: int,
    ) -> None:
        """The WRITE half — call only after all reads in the transaction
        are done. Creates the balance with `default_initial` on first
        touch, otherwise increments `used`.
        """
        now = datetime.now(timezone.utc)
        if snapshot.exists:
            current_used = (snapshot.to_dict() or {}).get("used", 0)
            transaction.update(doc_ref, {"used": current_used + delta_used, "updated_at": now})
        else:
            transaction.set(
                doc_ref,
                {
                    "employee_id": employee_id,
                    "leave_type_id": leave_type_id,
                    "year": year,
                    "initial": default_initial,
                    "accrued": 0,
                    "used": delta_used,
                    "created_at": now,
                    "updated_at": now,
                },
            )
