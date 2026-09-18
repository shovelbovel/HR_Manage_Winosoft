from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore

from app.models import AIAuditLogEntry, AIFunction

_COLLECTION = "ai_audit_log"


def _to_document(snapshot: firestore.DocumentSnapshot) -> AIAuditLogEntry:
    data = snapshot.to_dict() or {}
    return AIAuditLogEntry(id=snapshot.id, **data)


class AIAuditLogRepository:
    """Data access only for the `ai_audit_log` collection — scoped to
    Module 12's own audit requirement, not the full cross-app "Journal
    d'activités" (a separate, unbuilt feature — see the Module 12
    implementation plan's scope-decision note).
    """

    def __init__(self, db: firestore.Client):
        self._collection = db.collection(_COLLECTION)

    def create(self, *, user_id: str, function: AIFunction) -> AIAuditLogEntry:
        doc_ref = self._collection.document()
        doc_ref.set(
            {
                "user_id": user_id,
                "function": function.value,
                "created_at": datetime.now(timezone.utc),
            }
        )
        return _to_document(doc_ref.get())

    def list_recent(self, limit: int = 25) -> list[AIAuditLogEntry]:
        query = self._collection.order_by(
            "created_at", direction=firestore.Query.DESCENDING
        ).limit(limit)
        return [_to_document(snapshot) for snapshot in query.stream()]
