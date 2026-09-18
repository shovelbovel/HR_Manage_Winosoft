from __future__ import annotations

from datetime import date, datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models import ContractCategory, ContractType, TrialPeriodDocument, TrialPeriodStatus
from app.repositories.base import date_to_utc_datetime, paginate

_COLLECTION = "trial_periods"


def _to_document(snapshot: firestore.DocumentSnapshot) -> TrialPeriodDocument:
    data = snapshot.to_dict() or {}
    return TrialPeriodDocument(id=snapshot.id, **data)


class TrialPeriodsRepository:
    """Data access only for the `trial_periods` collection. The id is
    always the owning employee's id (see TrialPeriodDocument's docstring),
    so "does this employee have a trial period" is a document lookup, not
    a query.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def get_by_id(self, trial_period_id: str) -> TrialPeriodDocument | None:
        snapshot = self._collection.document(trial_period_id).get()
        return _to_document(snapshot) if snapshot.exists else None

    def get_by_employee_id(self, employee_id: str) -> TrialPeriodDocument | None:
        return self.get_by_id(employee_id)

    def list(
        self,
        statuses: tuple[TrialPeriodStatus, ...],
        cursor_id: str | None = None,
        limit: int = 25,
    ) -> list[TrialPeriodDocument]:
        query = self._collection.where(
            filter=FieldFilter("status", "in", [status.value for status in statuses])
        ).order_by("created_at")
        cursor_snapshot = self._collection.document(cursor_id).get() if cursor_id else None
        query = paginate(query, cursor_snapshot, limit)
        return [_to_document(snapshot) for snapshot in query.stream()]

    def create(
        self,
        *,
        employee_id: str,
        contract_type: ContractType,
        contract_category: ContractCategory | None,
        start_date: date,
        initial_end_date: date,
    ) -> TrialPeriodDocument:
        now = datetime.now(timezone.utc)
        doc_ref = self._collection.document(employee_id)
        data = {
            "employee_id": employee_id,
            "contract_type": contract_type.value,
            "contract_category": contract_category.value if contract_category else None,
            "start_date": date_to_utc_datetime(start_date),
            "initial_end_date": date_to_utc_datetime(initial_end_date),
            "extended_end_date": None,
            "status": TrialPeriodStatus.PENDING.value,
            "decision_reason": None,
            "decided_at": None,
            "decided_by": None,
            "created_at": now,
            "updated_at": now,
        }
        doc_ref.set(data)
        return _to_document(doc_ref.get())

    def decide(
        self,
        trial_period_id: str,
        *,
        status: TrialPeriodStatus,
        decided_by: str,
        reason: str | None,
        extended_end_date: date | None = None,
    ) -> TrialPeriodDocument:
        doc_ref = self._collection.document(trial_period_id)
        now = datetime.now(timezone.utc)
        data = {
            "status": status.value,
            "decision_reason": reason,
            "decided_at": now,
            "decided_by": decided_by,
            "updated_at": now,
        }
        if extended_end_date is not None:
            data["extended_end_date"] = date_to_utc_datetime(extended_end_date)
        doc_ref.update(data)
        return _to_document(doc_ref.get())
