from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models import CertificateDocument, CertificateType
from app.repositories.base import increment_counter, paginate

_COLLECTION = "certificates"


def _to_document(snapshot: firestore.DocumentSnapshot) -> CertificateDocument:
    data = snapshot.to_dict() or {}
    return CertificateDocument(id=snapshot.id, **data)


class CertificatesRepository:
    """Data access only for the `certificates` collection. Which fields go
    into `data_snapshot` is a business decision — that lives in
    app.services.certificates_service, not here.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def create(
        self,
        *,
        certificate_type: CertificateType,
        employee_id: str,
        department_id: str,
        generated_by: str,
        data_snapshot: dict,
    ) -> CertificateDocument:
        now = datetime.now(timezone.utc)
        # Same transactional-sequence pattern as EmployeesRepository's
        # matricule: "deux générations simultanées ne peuvent pas obtenir
        # le même numéro."
        seq = increment_counter(self._db, f"certificate_seq_{now.year}")
        number = f"ATT-{now.year}-{seq:04d}"

        doc_ref = self._collection.document()
        doc_ref.set(
            {
                "number": number,
                "certificate_type": certificate_type.value,
                "employee_id": employee_id,
                "department_id": department_id,
                "generated_by": generated_by,
                "data_snapshot": data_snapshot,
                "created_at": now,
            }
        )
        return _to_document(doc_ref.get())

    def get_by_id(self, certificate_id: str) -> CertificateDocument | None:
        snapshot = self._collection.document(certificate_id).get()
        if not snapshot.exists:
            return None
        return _to_document(snapshot)

    def list(
        self,
        *,
        department_id: str | None = None,
        employee_id: str | None = None,
        cursor_id: str | None = None,
        limit: int = 25,
    ) -> list[CertificateDocument]:
        # Scope boundary matched by firestore.indexes.json: at most one of
        # department_id/employee_id is expected at a time (mirrors
        # EmployeesRepository.list's same documented boundary).
        query = self._collection
        if department_id:
            query = query.where(filter=FieldFilter("department_id", "==", department_id))
        if employee_id:
            query = query.where(filter=FieldFilter("employee_id", "==", employee_id))
        query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
        cursor_snapshot = self._collection.document(cursor_id).get() if cursor_id else None
        query = paginate(query, cursor_snapshot, limit)
        return [_to_document(snapshot) for snapshot in query.stream()]
