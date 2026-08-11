"""Create the first admin user in the (emulator) Firestore database.

Idempotent: safe to run more than once. This is a manual stand-in for the
cahier des charges' full "script d'amorçage" (leave types, Moroccan holidays,
default settings, random admin password) — those land with their owning
modules. Run as a module (not as a bare script) so the `app` package
resolves:

    uv run python -m scripts.seed
    docker compose exec app uv run python -m scripts.seed
"""

from app.core.config import get_settings
from app.core.firestore_client import get_firestore_client
from app.core.security import hash_password
from app.models import UserRole
from app.repositories.users_repository import UsersRepository


def main() -> None:
    settings = get_settings()
    db = get_firestore_client()
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


if __name__ == "__main__":
    main()
