from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models import NotificationCategory, NotificationDocument
from app.repositories.base import paginate

_COLLECTION = "notifications"
_MARK_ALL_READ_BATCH_LIMIT = 500  # Firestore's own WriteBatch cap


def _to_document(snapshot: firestore.DocumentSnapshot) -> NotificationDocument:
    data = snapshot.to_dict() or {}
    return NotificationDocument(id=snapshot.id, **data)


class NotificationsRepository:
    """Data access only for the `notifications` collection — no business
    decisions. Who gets notified for what lives in
    app.services.notifications_service.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def create(
        self,
        *,
        recipient_user_id: str,
        category: NotificationCategory,
        message: str,
        link: str | None,
    ) -> NotificationDocument:
        doc_ref = self._collection.document()
        doc_ref.set(
            {
                "recipient_user_id": recipient_user_id,
                "category": category.value,
                "message": message,
                "link": link,
                "is_read": False,
                "created_at": datetime.now(timezone.utc),
            }
        )
        return _to_document(doc_ref.get())

    def create_many(
        self,
        *,
        recipient_user_ids: list[str],
        category: NotificationCategory,
        message: str,
        link: str | None,
    ) -> None:
        # "Alertes par destinataire": one document per recipient, not one
        # shared/broadcast row — each recipient gets independent read state.
        now = datetime.now(timezone.utc)
        batch = self._db.batch()
        for recipient_user_id in recipient_user_ids:
            doc_ref = self._collection.document()
            batch.set(
                doc_ref,
                {
                    "recipient_user_id": recipient_user_id,
                    "category": category.value,
                    "message": message,
                    "link": link,
                    "is_read": False,
                    "created_at": now,
                },
            )
        if recipient_user_ids:
            batch.commit()

    def list_recent(self, recipient_user_id: str, limit: int = 10) -> list[NotificationDocument]:
        query = (
            self._collection.where(
                filter=FieldFilter("recipient_user_id", "==", recipient_user_id)
            )
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [_to_document(snapshot) for snapshot in query.stream()]

    def list_all(
        self, recipient_user_id: str, cursor_id: str | None = None, limit: int = 25
    ) -> list[NotificationDocument]:
        query = self._collection.where(
            filter=FieldFilter("recipient_user_id", "==", recipient_user_id)
        ).order_by("created_at", direction=firestore.Query.DESCENDING)
        cursor_snapshot = self._collection.document(cursor_id).get() if cursor_id else None
        query = paginate(query, cursor_snapshot, limit)
        return [_to_document(snapshot) for snapshot in query.stream()]

    def count_unread(self, recipient_user_id: str) -> int:
        # Aggregation query: a single read regardless of how many unread
        # documents exist, unlike fetching them just to call len() on them.
        query = self._collection.where(
            filter=FieldFilter("recipient_user_id", "==", recipient_user_id)
        ).where(filter=FieldFilter("is_read", "==", False))
        result = query.count().get()
        return int(result[0][0].value)

    def get_by_id(self, notification_id: str) -> NotificationDocument | None:
        snapshot = self._collection.document(notification_id).get()
        if not snapshot.exists:
            return None
        return _to_document(snapshot)

    def mark_read(self, notification_id: str) -> NotificationDocument:
        doc_ref = self._collection.document(notification_id)
        doc_ref.update({"is_read": True})
        return _to_document(doc_ref.get())

    def mark_all_read(self, recipient_user_id: str) -> None:
        query = (
            self._collection.where(
                filter=FieldFilter("recipient_user_id", "==", recipient_user_id)
            )
            .where(filter=FieldFilter("is_read", "==", False))
            .limit(_MARK_ALL_READ_BATCH_LIMIT)
        )
        batch = self._db.batch()
        found = False
        for snapshot in query.stream():
            found = True
            batch.update(snapshot.reference, {"is_read": True})
        if found:
            batch.commit()
