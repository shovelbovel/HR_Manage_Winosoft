"""Firestore-substitute mechanisms shared by every repository.

Firestore has no unique constraints, no joins, no LIKE operator, no cheap
COUNT(*), and no efficient OFFSET. The cahier des charges centralizes the
substitutes for each in the data-access layer so they are implemented once
and never reimplemented ad hoc by a service. See "Substituts aux fonctions
relationnelles absentes" in the cahier des charges.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from google.cloud import firestore

_UNIQUES_COLLECTION = "_uniques"
_COUNTERS_COLLECTION = "_counters"


def date_to_utc_datetime(value: date) -> datetime:
    """A date-only value is stored as midnight UTC, per the cahier des
    charges' Firestore conventions: "les dates sont stockées en horodatage
    UTC. Une date seule est enregistrée à minuit UTC."
    """
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)


class AlreadyExistsError(Exception):
    """Raised when a unique-lock creation fails because the value is taken."""

    def __init__(self, field: str, value: str):
        self.field = field
        self.value = value
        super().__init__(f"{field}={value!r} is already in use")


def _unique_key(field: str, value: str) -> str:
    # Prefixed by field so distinct fields (email, matricule, cin, ...) can
    # share the _uniques collection without key collisions.
    return f"{field}:{value}"


def acquire_unique_lock(db: firestore.Client, field: str, value: str, owner_id: str) -> None:
    """Reserve a unique value for `field` (e.g. "email"), pointing at owner_id.

    Raises AlreadyExistsError if the value is already reserved. Must be
    released via release_unique_lock when the owning document is edited to a
    different value or deactivated/deleted, or the value stays blocked
    forever.
    """
    doc_ref = db.collection(_UNIQUES_COLLECTION).document(_unique_key(field, value))
    try:
        doc_ref.create({"owner_id": owner_id})
    except Exception as exc:  # google.api_core.exceptions.AlreadyExists
        if type(exc).__name__ == "AlreadyExists":
            raise AlreadyExistsError(field, value) from exc
        raise


def release_unique_lock(db: firestore.Client, field: str, value: str) -> None:
    db.collection(_UNIQUES_COLLECTION).document(_unique_key(field, value)).delete()


def get_unique_lock_owner(db: firestore.Client, field: str, value: str) -> str | None:
    snapshot = db.collection(_UNIQUES_COLLECTION).document(_unique_key(field, value)).get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict().get("owner_id")


def increment_counter(db: firestore.Client, counter_name: str, delta: int = 1) -> int:
    """Transactional read-modify-write on _counters/{counter_name}.

    Substitutes for a cheap COUNT(*). Can drift if a write fails outside the
    transaction boundary — a nightly reconciliation job is expected to
    recompute counters from source collections (not implemented in this
    scaffold; see cahier des charges "COUNT(*) gratuit").
    """
    doc_ref = db.collection(_COUNTERS_COLLECTION).document(counter_name)

    @firestore.transactional
    def _bump(transaction: firestore.Transaction) -> int:
        snapshot = doc_ref.get(transaction=transaction)
        current = snapshot.get("value") if snapshot.exists else 0
        new_value = (current or 0) + delta
        transaction.set(doc_ref, {"value": new_value}, merge=True)
        return new_value

    return _bump(db.transaction())


def get_counter_value(db: firestore.Client, counter_name: str) -> int:
    """Plain read of _counters/{counter_name} — no transaction, since a
    dashboard KPI card doesn't need the stricter consistency
    increment_counter's transaction provides for writers.
    """
    snapshot = db.collection(_COUNTERS_COLLECTION).document(counter_name).get()
    if not snapshot.exists:
        return 0
    return snapshot.get("value") or 0


def build_search_tokens(*fields: str) -> list[str]:
    """Lowercase prefix tokens for the fields, substituting SQL LIKE.

    Matching is by-prefix only: searching mid-word or with typo tolerance
    is out of scope without an external search engine.
    """
    tokens: set[str] = set()
    for field in fields:
        if not field:
            continue
        normalized = field.strip().lower()
        for word in normalized.split():
            for i in range(1, len(word) + 1):
                tokens.add(word[:i])
    return sorted(tokens)


def paginate(
    query: firestore.Query,
    cursor: firestore.DocumentSnapshot | None,
    limit: int,
) -> firestore.Query:
    """Apply cursor-based pagination to a query.

    Firestore has no efficient OFFSET, so navigation is "next page" only via
    start_after(the last document snapshot of the previous page) — there is
    no jump-to-page-N API surface. Callers are responsible for keeping the
    last snapshot of a page (e.g. behind an opaque token) to pass back in as
    `cursor` for the next page.
    """
    if cursor is not None:
        query = query.start_after(cursor)
    return query.limit(limit)
