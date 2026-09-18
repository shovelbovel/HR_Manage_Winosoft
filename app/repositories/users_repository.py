from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.models import UserDocument, UserRole
from app.repositories.base import (
    acquire_unique_lock,
    build_search_tokens,
    get_unique_lock_owner,
    paginate,
    release_unique_lock,
)

_COLLECTION = "users"
_EMAIL_FIELD = "email"


def _to_document(snapshot: firestore.DocumentSnapshot) -> UserDocument:
    data = snapshot.to_dict() or {}
    return UserDocument(id=snapshot.id, **data)


class UsersRepository:
    """Data access only for the `users` collection — no business decisions.
    Business rules (lockout thresholds, what counts as "authenticated") live
    in app.services.auth_service, per the cahier des charges layering rule.
    """

    def __init__(self, db: firestore.Client):
        self._db = db
        self._collection = db.collection(_COLLECTION)

    def get_by_id(self, user_id: str) -> UserDocument | None:
        snapshot = self._collection.document(user_id).get()
        if not snapshot.exists:
            return None
        return _to_document(snapshot)

    def get_by_email(self, email: str) -> UserDocument | None:
        # The uniqueness lock doubles as the email -> id lookup index, so no
        # extra query (and no extra index) is needed for login-by-email.
        user_id = get_unique_lock_owner(self._db, _EMAIL_FIELD, email)
        if user_id is None:
            return None
        return self.get_by_id(user_id)

    def create(
        self,
        *,
        email: str,
        hashed_password: str,
        role: UserRole,
        employee_id: str | None = None,
        department_id: str | None = None,
    ) -> UserDocument:
        doc_ref = self._collection.document()
        acquire_unique_lock(self._db, _EMAIL_FIELD, email, owner_id=doc_ref.id)
        try:
            now = datetime.now(timezone.utc)
            data = {
                "employee_id": employee_id,
                "email": email,
                "hashed_password": hashed_password,
                "role": role.value,
                "is_active": True,
                "department_id": department_id,
                "search_tokens": build_search_tokens(email),
                "failed_login_attempts": 0,
                "locked_until": None,
                "last_login": None,
                "created_at": now,
                "updated_at": now,
            }
            doc_ref.set(data)
        except Exception:
            release_unique_lock(self._db, _EMAIL_FIELD, email)
            raise
        return _to_document(doc_ref.get())

    def increment_failed_attempts(self, user_id: str) -> int:
        doc_ref = self._collection.document(user_id)

        @firestore.transactional
        def _bump(transaction: firestore.Transaction) -> int:
            snapshot = doc_ref.get(transaction=transaction)
            current = (snapshot.to_dict() or {}).get("failed_login_attempts", 0)
            new_value = current + 1
            transaction.update(
                doc_ref,
                {
                    "failed_login_attempts": new_value,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            return new_value

        return _bump(self._db.transaction())

    def reset_failed_attempts(self, user_id: str) -> None:
        self._collection.document(user_id).update(
            {
                "failed_login_attempts": 0,
                "locked_until": None,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    def set_lockout(self, user_id: str, locked_until: datetime) -> None:
        self._collection.document(user_id).update(
            {"locked_until": locked_until, "updated_at": datetime.now(timezone.utc)}
        )

    def set_active(self, user_id: str, is_active: bool) -> None:
        user = self.get_by_id(user_id)
        if user is None:
            return
        self._collection.document(user_id).update(
            {"is_active": is_active, "updated_at": datetime.now(timezone.utc)}
        )
        # Deactivating a user frees its email for reuse by a future account,
        # per the cahier des charges' "libéré à la modification ou à la
        # désactivation" rule for unique locks. Reactivating must re-claim
        # it, or get_by_email (which resolves through this lock, not a
        # field query) can never find the account again even though it's
        # active — this was unreachable in practice until Module 11 added
        # an actual activate-after-deactivate UI path to exercise it.
        # Raises AlreadyExistsError if another account has since claimed
        # the email during the free-for-reuse window — a real conflict,
        # not swallowed.
        if not is_active and user.is_active:
            release_unique_lock(self._db, _EMAIL_FIELD, user.email)
        elif is_active and not user.is_active:
            acquire_unique_lock(self._db, _EMAIL_FIELD, user.email, owner_id=user_id)

    def touch_last_login(self, user_id: str) -> None:
        self._collection.document(user_id).update(
            {"last_login": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}
        )

    def list_admins(self) -> list[UserDocument]:
        """Notification fan-out target — pure multi-equality (role +
        is_active), no composite index needed."""
        query = self._collection.where(filter=FieldFilter("role", "==", UserRole.ADMIN.value)).where(
            filter=FieldFilter("is_active", "==", True)
        )
        return [_to_document(snapshot) for snapshot in query.stream()]

    def list_active_managers_for_department(self, department_id: str) -> list[UserDocument]:
        """Notification fan-out target — pure multi-equality (role +
        department_id + is_active), no composite index needed."""
        query = (
            self._collection.where(filter=FieldFilter("role", "==", UserRole.MANAGER.value))
            .where(filter=FieldFilter("department_id", "==", department_id))
            .where(filter=FieldFilter("is_active", "==", True))
        )
        return [_to_document(snapshot) for snapshot in query.stream()]

    def list(self, cursor_id: str | None = None, limit: int = 25) -> list[UserDocument]:
        query = self._collection.order_by("email")
        cursor_snapshot = self._collection.document(cursor_id).get() if cursor_id else None
        query = paginate(query, cursor_snapshot, limit)
        return [_to_document(snapshot) for snapshot in query.stream()]

    def set_password(self, user_id: str, hashed_password: str) -> None:
        self._collection.document(user_id).update(
            {"hashed_password": hashed_password, "updated_at": datetime.now(timezone.utc)}
        )

    def get_by_employee_id(self, employee_id: str) -> UserDocument | None:
        """The login account linked to an employee, if any — Module 11
        (Paramètres > Utilisateurs) doesn't exist yet to guarantee one, so
        this can legitimately return None."""
        query = self._collection.where(
            filter=FieldFilter("employee_id", "==", employee_id)
        ).limit(1)
        results = list(query.stream())
        return _to_document(results[0]) if results else None
