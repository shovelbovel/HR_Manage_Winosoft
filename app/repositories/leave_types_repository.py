from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore

from app.models import LeaveTypeDocument
from app.repositories.base import acquire_unique_lock, release_unique_lock

_COLLECTION = "leave_types"
_CODE_FIELD = "code"


def _to_document(snapshot: firestore.DocumentSnapshot) -> LeaveTypeDocument:
    data = snapshot.to_dict() or {}
    return LeaveTypeDocument(id=snapshot.id, **data)


class LeaveTypesRepository:
    """Read-only in this pass — leave_types is seeded by scripts/seed.py.
    Module 11 (Settings > Congés) will add create/update/delete later.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def list(self) -> list[LeaveTypeDocument]:
        return [_to_document(snapshot) for snapshot in self._collection.order_by("name").stream()]

    def get_by_id(self, leave_type_id: str) -> LeaveTypeDocument | None:
        snapshot = self._collection.document(leave_type_id).get()
        if not snapshot.exists:
            return None
        return _to_document(snapshot)

    def create(
        self,
        *,
        code: str,
        name: str,
        default_days_per_year: int | None,
        is_deductible: bool,
        requires_justification: bool,
    ) -> LeaveTypeDocument:
        # Unlike upsert_by_code (seed-only, no lock — nothing to race with
        # there), this is a real admin-facing create endpoint (Module 11),
        # so it needs the same acquire_unique_lock/AlreadyExistsError
        # pattern as department code / employee CIN / user email.
        doc_ref = self._collection.document()
        acquire_unique_lock(self._db, _CODE_FIELD, code, owner_id=doc_ref.id)
        try:
            now = datetime.now(timezone.utc)
            doc_ref.set(
                {
                    "code": code,
                    "name": name,
                    "default_days_per_year": default_days_per_year,
                    "is_deductible": is_deductible,
                    "requires_justification": requires_justification,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        except Exception:
            release_unique_lock(self._db, _CODE_FIELD, code)
            raise
        return _to_document(doc_ref.get())

    def update(
        self,
        leave_type_id: str,
        *,
        name: str,
        default_days_per_year: int | None,
        is_deductible: bool,
        requires_justification: bool,
    ) -> LeaveTypeDocument:
        doc_ref = self._collection.document(leave_type_id)
        doc_ref.update(
            {
                "name": name,
                "default_days_per_year": default_days_per_year,
                "is_deductible": is_deductible,
                "requires_justification": requires_justification,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return _to_document(doc_ref.get())

    def upsert_by_code(
        self,
        *,
        code: str,
        name: str,
        default_days_per_year: int | None,
        is_deductible: bool,
        requires_justification: bool,
    ) -> LeaveTypeDocument:
        """Used only by scripts/seed.py — idempotent seeding keyed by
        `code` (not a real _uniques lock, since this collection has no
        create/edit endpoint for a concurrent write to race with).
        """
        existing = next((lt for lt in self.list() if lt.code == code), None)
        now = datetime.now(timezone.utc)
        data = {
            "code": code,
            "name": name,
            "default_days_per_year": default_days_per_year,
            "is_deductible": is_deductible,
            "requires_justification": requires_justification,
            "updated_at": now,
        }
        if existing is not None:
            doc_ref = self._collection.document(existing.id)
            doc_ref.update(data)
        else:
            doc_ref = self._collection.document()
            data["created_at"] = now
            doc_ref.set(data)
        return _to_document(doc_ref.get())
