from __future__ import annotations

from google.cloud import firestore

from app.models import HolidayDocument

_COLLECTION = "holidays"


def _to_document(snapshot: firestore.DocumentSnapshot) -> HolidayDocument:
    data = snapshot.to_dict() or {}
    return HolidayDocument(id=snapshot.id, **data)


class HolidaysRepository:
    """Read-only in this pass — holidays is seeded by scripts/seed.py with
    fixed grégorien dates only. Module 11 (Settings > Congés) will add
    create/update/delete (including manual yearly religious-holiday entry)
    later.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def list(self) -> list[HolidayDocument]:
        return [_to_document(snapshot) for snapshot in self._collection.stream()]

    def upsert_recurring(self, *, name: str, month: int, day: int) -> HolidayDocument:
        """Used only by scripts/seed.py — idempotent seeding keyed by
        (month, day), since that's the natural identity of a fixed
        grégorien holiday.
        """
        existing = next(
            (h for h in self.list() if h.is_recurring and h.month == month and h.day == day),
            None,
        )
        data = {"name": name, "is_recurring": True, "month": month, "day": day, "year": None}
        if existing is not None:
            doc_ref = self._collection.document(existing.id)
            doc_ref.update(data)
        else:
            doc_ref = self._collection.document()
            doc_ref.set(data)
        return _to_document(doc_ref.get())

    def create(
        self, *, name: str, is_recurring: bool, month: int, day: int, year: int | None
    ) -> HolidayDocument:
        doc_ref = self._collection.document()
        doc_ref.set(
            {
                "name": name,
                "is_recurring": is_recurring,
                "month": month,
                "day": day,
                "year": year,
            }
        )
        return _to_document(doc_ref.get())

    def delete(self, holiday_id: str) -> None:
        self._collection.document(holiday_id).delete()
