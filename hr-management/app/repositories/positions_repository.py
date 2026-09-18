from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models import PositionDocument
from app.repositories.base import paginate

_COLLECTION = "positions"


def _to_document(snapshot: firestore.DocumentSnapshot) -> PositionDocument:
    data = snapshot.to_dict() or {}
    return PositionDocument(id=snapshot.id, **data)


class PositionsRepository:
    """Data access only for the `positions` collection — no business
    decisions. The "cannot delete while occupied" rule and the
    `max_occupants` cap live in app.services.positions_service /
    app.services.employees_service, per the cahier des charges layering
    rule.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def get_by_id(self, position_id: str) -> PositionDocument | None:
        snapshot = self._collection.document(position_id).get()
        if not snapshot.exists:
            return None
        return _to_document(snapshot)

    def list(
        self,
        department_id: str | None,
        cursor_id: str | None,
        limit: int = 25,
    ) -> list[PositionDocument]:
        query = self._collection
        if department_id:
            query = query.where(filter=FieldFilter("department_id", "==", department_id))
        query = query.order_by("title")
        cursor_snapshot = self._collection.document(cursor_id).get() if cursor_id else None
        query = paginate(query, cursor_snapshot, limit)
        return [_to_document(snapshot) for snapshot in query.stream()]

    def create(self, *, department_id: str, department_name: str, title: str,
               max_occupants: int | None) -> PositionDocument:
        doc_ref = self._collection.document()
        now = datetime.now(timezone.utc)
        data = {
            "department_id": department_id,
            "department_name": department_name,
            "title": title,
            "max_occupants": max_occupants,
            "occupant_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        doc_ref.set(data)
        return _to_document(doc_ref.get())

    def update(
        self, position_id: str, *, title: str, max_occupants: int | None
    ) -> PositionDocument:
        doc_ref = self._collection.document(position_id)
        doc_ref.update(
            {
                "title": title,
                "max_occupants": max_occupants,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return _to_document(doc_ref.get())

    def delete(self, position_id: str) -> None:
        self._collection.document(position_id).delete()

    def increment_occupant_count(self, position_id: str, delta: int = 1) -> int:
        doc_ref = self._collection.document(position_id)

        @firestore.transactional
        def _bump(transaction: firestore.Transaction) -> int:
            snapshot = doc_ref.get(transaction=transaction)
            current = (snapshot.to_dict() or {}).get("occupant_count", 0)
            new_value = current + delta
            transaction.update(
                doc_ref,
                {"occupant_count": new_value, "updated_at": datetime.now(timezone.utc)},
            )
            return new_value

        return _bump(self._db.transaction())
