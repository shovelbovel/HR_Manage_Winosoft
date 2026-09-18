"""Create the first admin user plus reference data (leave types, fixed
Moroccan holidays) in the (emulator) Firestore database.

Idempotent: safe to run more than once. This is a manual stand-in for the
cahier des charges' full "script d'amorçage" (default settings, random admin
password) — the rest lands with its owning module (Module 11). Run as a
module (not as a bare script) so the `app` package resolves:

    uv run python -m scripts.seed
    docker compose exec app uv run python -m scripts.seed
"""

from app.core.config import get_settings
from app.core.firestore_client import get_firestore_client
from app.core.security import hash_password
from app.models import UserRole
from app.repositories.holidays_repository import HolidaysRepository
from app.repositories.leave_types_repository import LeaveTypesRepository
from app.repositories.users_repository import UsersRepository

# Cahier des charges Module 6, "Types de congés" table (page 21).
_LEAVE_TYPES = [
    {
        "code": "ANNUAL",
        "name": "Congé annuel",
        "default_days_per_year": 18,
        "is_deductible": True,
        "requires_justification": False,
    },
    {
        "code": "SICK",
        "name": "Maladie",
        "default_days_per_year": None,
        "is_deductible": False,
        "requires_justification": True,
    },
    {
        "code": "MATERNITY",
        "name": "Maternité",
        "default_days_per_year": 98,
        "is_deductible": False,
        "requires_justification": True,
    },
    {
        "code": "PATERNITY",
        "name": "Paternité",
        "default_days_per_year": 3,
        "is_deductible": False,
        "requires_justification": True,
    },
    {
        "code": "MARRIAGE",
        "name": "Mariage",
        "default_days_per_year": 4,
        "is_deductible": False,
        "requires_justification": True,
    },
    {
        "code": "BEREAVEMENT",
        "name": "Décès",
        "default_days_per_year": 3,
        "is_deductible": False,
        "requires_justification": True,
    },
    {
        "code": "UNPAID",
        "name": "Sans solde",
        "default_days_per_year": None,
        "is_deductible": False,
        "requires_justification": False,
    },
    {
        "code": "EXCEPTIONAL",
        "name": "Exceptionnel",
        "default_days_per_year": None,
        "is_deductible": False,
        "requires_justification": False,
    },
]

# Fixed grégorien Moroccan public holidays only — religious/lunar holidays
# need manual yearly entry per the cahier des charges' "Réserve sur les
# jours fériés religieux" and that entry screen (Module 11) doesn't exist
# yet.
_HOLIDAYS = [
    ("Nouvel an", 1, 1),
    ("Fête du Travail", 5, 1),
    ("Fête du Trône", 7, 30),
    ("Révolution du Roi et du Peuple", 8, 20),
    ("Fête de la Jeunesse", 8, 21),
    ("Marche Verte", 11, 6),
    ("Fête de l'Indépendance", 11, 18),
]


def _seed_admin(settings, db) -> None:
    users = UsersRepository(db)
    existing = users.get_by_email(settings.seed_admin_email)
    if existing is not None:
        print(f"Admin user already exists: {settings.seed_admin_email} (id={existing.id})")
        return

    admin = users.create(
        email=settings.seed_admin_email,
        hashed_password=hash_password(settings.seed_admin_password, settings=settings),
        role=UserRole.ADMIN,
    )
    print(f"Created admin user: {admin.email} (id={admin.id})")
    print(f"Password: {settings.seed_admin_password}")


def _seed_leave_types(db) -> None:
    leave_types = LeaveTypesRepository(db)
    for entry in _LEAVE_TYPES:
        leave_types.upsert_by_code(**entry)
    print(f"Seeded {len(_LEAVE_TYPES)} leave types.")


def _seed_holidays(db) -> None:
    holidays = HolidaysRepository(db)
    for name, month, day in _HOLIDAYS:
        holidays.upsert_recurring(name=name, month=month, day=day)
    print(f"Seeded {len(_HOLIDAYS)} fixed holidays.")


def main() -> None:
    settings = get_settings()
    db = get_firestore_client()
    _seed_admin(settings, db)
    _seed_leave_types(db)
    _seed_holidays(db)


if __name__ == "__main__":
    main()
