from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models import ContractCategory, ContractType, EmployeeDocument, EmployeeStatus
from app.repositories.base import (
    acquire_unique_lock,
    build_search_tokens,
    date_to_utc_datetime,
    get_unique_lock_owner,
    increment_counter,
    paginate,
    release_unique_lock,
)

_COLLECTION = "employees"
_CIN_FIELD = "cin"
_EMAIL_FIELD = "professional_email"
_MATRICULE_FIELD = "matricule"


def _to_document(snapshot: firestore.DocumentSnapshot) -> EmployeeDocument:
    data = snapshot.to_dict() or {}
    return EmployeeDocument(id=snapshot.id, **data)


def _optional_utc(value: date | None) -> datetime | None:
    return date_to_utc_datetime(value) if value is not None else None


class EmployeesRepository:
    """Data access only for the `employees` collection — no business
    decisions. Matricule generation and unique-lock bookkeeping are
    mechanical (not judgment calls) so they live here, same as
    UsersRepository.create's email lock. Position/department capacity
    checks, status-transition rules, and counter propagation live in
    app.services.employees_service.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def get_by_id(self, employee_id: str) -> EmployeeDocument | None:
        snapshot = self._collection.document(employee_id).get()
        if not snapshot.exists:
            return None
        return _to_document(snapshot)

    def get_by_cin(self, cin: str) -> EmployeeDocument | None:
        employee_id = get_unique_lock_owner(self._db, _CIN_FIELD, cin)
        return self.get_by_id(employee_id) if employee_id else None

    def get_by_professional_email(self, email: str) -> EmployeeDocument | None:
        employee_id = get_unique_lock_owner(self._db, _EMAIL_FIELD, email)
        return self.get_by_id(employee_id) if employee_id else None

    def list(
        self,
        *,
        department_id: str | None = None,
        status: EmployeeStatus | None = None,
        contract_type: ContractType | None = None,
        search_prefix: str | None = None,
        cursor_id: str | None = None,
        limit: int = 25,
    ) -> list[EmployeeDocument]:
        # Scope boundary, matched by firestore.indexes.json: at most ONE of
        # department_id/status/contract_type is expected combined with
        # search_prefix at a time. Combining two of those three equality
        # filters together is not index-declared and will raise at the
        # emulator/Firestore level ("the query requires an index") — the
        # router only ever passes one filter dimension plus search.
        query = self._collection
        if department_id:
            query = query.where(filter=FieldFilter("department_id", "==", department_id))
        if status:
            query = query.where(filter=FieldFilter("status", "==", status.value))
        if contract_type:
            query = query.where(filter=FieldFilter("contract_type", "==", contract_type.value))
        if search_prefix:
            query = query.where(
                filter=FieldFilter(
                    "search_tokens", "array_contains", search_prefix.strip().lower()
                )
            )
        query = query.order_by("last_name")
        cursor_snapshot = self._collection.document(cursor_id).get() if cursor_id else None
        query = paginate(query, cursor_snapshot, limit)
        return [_to_document(snapshot) for snapshot in query.stream()]

    def list_contracts_expiring_within(
        self, days: int, department_id: str | None = None
    ) -> list[EmployeeDocument]:
        """Live query, not counter-backed — cahier des charges Module 2:
        "Contrats expirant... Requête sur contract_end_date à 30 jours."
        Two range clauses on the *same* field (contract_end_date) don't
        need a composite index by themselves; department_id does when
        supplied — see firestore.indexes.json.
        """
        today = date_to_utc_datetime(date.today())
        cutoff = date_to_utc_datetime(date.today() + timedelta(days=days))
        query = self._collection.where(
            filter=FieldFilter("contract_end_date", ">=", today)
        ).where(filter=FieldFilter("contract_end_date", "<=", cutoff))
        if department_id:
            query = query.where(filter=FieldFilter("department_id", "==", department_id))
        query = query.order_by("contract_end_date")
        return [_to_document(snapshot) for snapshot in query.stream()]

    def list_new_hires_since(
        self, start_date: date, department_id: str | None = None
    ) -> list[EmployeeDocument]:
        """Live query — cahier des charges Module 2: "Nouveaux employés du
        mois... Requête sur created_at."""
        cutoff = date_to_utc_datetime(start_date)
        query = self._collection.where(filter=FieldFilter("created_at", ">=", cutoff))
        if department_id:
            query = query.where(filter=FieldFilter("department_id", "==", department_id))
        query = query.order_by("created_at")
        return [_to_document(snapshot) for snapshot in query.stream()]

    def list_birthdays_this_month(
        self, month: int, department_id: str | None = None
    ) -> list[EmployeeDocument]:
        """Equality-only (birth_month, optionally department_id) — no
        composite index needed. Uses the birth_month field the cahier des
        charges added specifically to "alimenter la carte anniversaires du
        mois" without reading the whole collection.
        """
        query = self._collection.where(filter=FieldFilter("birth_month", "==", month))
        if department_id:
            query = query.where(filter=FieldFilter("department_id", "==", department_id))
        return [_to_document(snapshot) for snapshot in query.stream()]

    def list_for_distribution(
        self, department_id: str | None = None, limit: int = 250
    ) -> list[EmployeeDocument]:
        """Bounded fetch backing the dashboard's department/contract-type
        distribution charts. Not counter-backed — the spec's stated target
        scale ("moins de deux cents salariés") makes a capped read here
        proportionate, unlike the KPI cards. Includes inactive employees —
        "should this report exclude them" is a business decision the
        service layer makes, not this repository.
        """
        query = self._collection
        if department_id:
            query = query.where(filter=FieldFilter("department_id", "==", department_id))
        query = query.limit(limit)
        return [_to_document(snapshot) for snapshot in query.stream()]

    def create(
        self,
        *,
        first_name: str,
        last_name: str,
        cin: str,
        birth_date: date,
        professional_email: str,
        phone: str,
        department_id: str,
        department_name: str,
        position_id: str,
        position_title: str,
        hire_date: date,
        contract_type: ContractType,
        contract_category: ContractCategory | None,
        contract_start_date: date,
        contract_end_date: date | None,
        gross_salary_encrypted: str,
        rib_encrypted: str,
        cnss_number: str,
        emergency_contact_name: str,
        emergency_contact_phone: str,
        internal_notes: str | None,
    ) -> EmployeeDocument:
        now = datetime.now(timezone.utc)
        seq = increment_counter(self._db, f"matricule_seq_{now.year}")
        matricule = f"EMP-{now.year}-{seq:04d}"

        doc_ref = self._collection.document()
        acquired: list[tuple[str, str]] = []
        try:
            # matricule is locked defense-in-depth even though the
            # per-year sequence already guarantees uniqueness, per the
            # cahier des charges' uniqueness rule explicitly naming it
            # alongside cin/professional_email.
            for field, value in (
                (_MATRICULE_FIELD, matricule),
                (_CIN_FIELD, cin),
                (_EMAIL_FIELD, professional_email),
            ):
                acquire_unique_lock(self._db, field, value, owner_id=doc_ref.id)
                acquired.append((field, value))

            birth_date_dt = date_to_utc_datetime(birth_date)
            data = {
                "matricule": matricule,
                "first_name": first_name,
                "last_name": last_name,
                "cin": cin,
                "birth_date": birth_date_dt,
                "birth_month": birth_date_dt.month,
                "professional_email": professional_email,
                "phone": phone,
                "department_id": department_id,
                "department_name": department_name,
                "position_id": position_id,
                "position_title": position_title,
                "hire_date": date_to_utc_datetime(hire_date),
                "contract_type": contract_type.value,
                "contract_category": contract_category.value if contract_category else None,
                "contract_start_date": date_to_utc_datetime(contract_start_date),
                "contract_end_date": _optional_utc(contract_end_date),
                "status": EmployeeStatus.TRIAL.value,
                "gross_salary_encrypted": gross_salary_encrypted,
                "rib_encrypted": rib_encrypted,
                "cnss_number": cnss_number,
                "emergency_contact_name": emergency_contact_name,
                "emergency_contact_phone": emergency_contact_phone,
                "internal_notes": internal_notes,
                "search_tokens": build_search_tokens(first_name, last_name, cin, matricule),
                "photo_url": None,
                "created_at": now,
                "updated_at": now,
            }
            doc_ref.set(data)
        except Exception:
            for field, value in acquired:
                release_unique_lock(self._db, field, value)
            raise

        return _to_document(doc_ref.get())

    def update(
        self,
        employee_id: str,
        *,
        first_name: str,
        last_name: str,
        cin: str,
        birth_date: date,
        professional_email: str,
        phone: str,
        hire_date: date,
        contract_type: ContractType,
        contract_category: ContractCategory | None,
        contract_start_date: date,
        contract_end_date: date | None,
        gross_salary_encrypted: str,
        rib_encrypted: str,
        cnss_number: str,
        emergency_contact_name: str,
        emergency_contact_phone: str,
        internal_notes: str | None,
    ) -> EmployeeDocument:
        existing = self.get_by_id(employee_id)
        if existing is None:
            raise ValueError(f"Employee {employee_id} does not exist")

        doc_ref = self._collection.document(employee_id)
        cin_changed = cin != existing.cin
        email_changed = professional_email != existing.professional_email
        acquired: list[tuple[str, str]] = []
        try:
            if cin_changed:
                acquire_unique_lock(self._db, _CIN_FIELD, cin, owner_id=employee_id)
                acquired.append((_CIN_FIELD, cin))
            if email_changed:
                acquire_unique_lock(
                    self._db, _EMAIL_FIELD, professional_email, owner_id=employee_id
                )
                acquired.append((_EMAIL_FIELD, professional_email))

            birth_date_dt = date_to_utc_datetime(birth_date)
            data = {
                "first_name": first_name,
                "last_name": last_name,
                "cin": cin,
                "birth_date": birth_date_dt,
                "birth_month": birth_date_dt.month,
                "professional_email": professional_email,
                "phone": phone,
                "hire_date": date_to_utc_datetime(hire_date),
                "contract_type": contract_type.value,
                "contract_category": contract_category.value if contract_category else None,
                "contract_start_date": date_to_utc_datetime(contract_start_date),
                "contract_end_date": _optional_utc(contract_end_date),
                "gross_salary_encrypted": gross_salary_encrypted,
                "rib_encrypted": rib_encrypted,
                "cnss_number": cnss_number,
                "emergency_contact_name": emergency_contact_name,
                "emergency_contact_phone": emergency_contact_phone,
                "internal_notes": internal_notes,
                "search_tokens": build_search_tokens(
                    first_name, last_name, cin, existing.matricule
                ),
                "updated_at": datetime.now(timezone.utc),
            }
            doc_ref.update(data)
        except Exception:
            for field, value in acquired:
                release_unique_lock(self._db, field, value)
            raise

        # Only release the OLD lock values once the write has succeeded, so
        # a failed update never leaves neither the old nor new value locked.
        if cin_changed:
            release_unique_lock(self._db, _CIN_FIELD, existing.cin)
        if email_changed:
            release_unique_lock(self._db, _EMAIL_FIELD, existing.professional_email)

        return _to_document(doc_ref.get())

    def set_status(self, employee_id: str, status: EmployeeStatus) -> EmployeeDocument:
        doc_ref = self._collection.document(employee_id)
        doc_ref.update({"status": status.value, "updated_at": datetime.now(timezone.utc)})
        return _to_document(doc_ref.get())
