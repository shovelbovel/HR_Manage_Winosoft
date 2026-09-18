from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore

from app.models import AISettings, CompanySettings

_COLLECTION = "settings"
_COMPANY_DOC_ID = "company"
_AI_DOC_ID = "assistant"


class SettingsRepository:
    """Data access only for the `settings` collection. The document id is
    the parameter key itself (cahier des charges: "l'identifiant du
    document est la clé du paramètre : lecture directe sans requête"), so
    every read here is a direct get(), never a query.
    """

    def __init__(self, db: firestore.Client):
        self._collection = db.collection(_COLLECTION)

    def get_company(self) -> CompanySettings | None:
        snapshot = self._collection.document(_COMPANY_DOC_ID).get()
        if not snapshot.exists:
            return None
        return CompanySettings(id=snapshot.id, **(snapshot.to_dict() or {}))

    def set_company(
        self, *, name: str, address: str, ice: str, rc: str, if_number: str
    ) -> CompanySettings:
        doc_ref = self._collection.document(_COMPANY_DOC_ID)
        doc_ref.set(
            {
                "name": name,
                "address": address,
                "ice": ice,
                "rc": rc,
                "if_number": if_number,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return CompanySettings(id=doc_ref.id, **(doc_ref.get().to_dict() or {}))

    def get_ai(self) -> AISettings | None:
        snapshot = self._collection.document(_AI_DOC_ID).get()
        if not snapshot.exists:
            return None
        return AISettings(id=snapshot.id, **(snapshot.to_dict() or {}))

    def set_ai(
        self, *, enabled: bool, daily_quota_per_user: int, monthly_quota_global: int
    ) -> AISettings:
        doc_ref = self._collection.document(_AI_DOC_ID)
        doc_ref.set(
            {
                "enabled": enabled,
                "daily_quota_per_user": daily_quota_per_user,
                "monthly_quota_global": monthly_quota_global,
            }
        )
        return AISettings(id=doc_ref.id, **(doc_ref.get().to_dict() or {}))
