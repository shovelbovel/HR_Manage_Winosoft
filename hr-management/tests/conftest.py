import os

import httpx
import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.core.config import get_settings
from app.core.dependencies import get_db
from app.core.firestore_client import get_firestore_client
from app.core.security import hash_password
from app.main import create_app
from app.models import UserRole
from app.repositories.users_repository import UsersRepository

ADMIN_EMAIL = "admin@hr-management-test.dev"
ADMIN_PASSWORD = "CorrectHorse123!"


@pytest.fixture(scope="session", autouse=True)
def _require_emulator():
    # Hard guardrail: pytest must never be able to touch a real Firestore
    # project. See cahier des charges "Tests: pytest, émulateur Firestore —
    # recette automatisée sans dépendre de la base de production."
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        pytest.exit(
            "FIRESTORE_EMULATOR_HOST is not set. Refusing to run tests without "
            "an emulator target — start it with `docker compose up firebase-emulators` "
            "and set FIRESTORE_EMULATOR_HOST (see .env.example) before running pytest.",
            returncode=1,
        )


@pytest.fixture(scope="session")
def db() -> firestore.Client:
    return get_firestore_client()


def _wipe_emulator(db: firestore.Client) -> None:
    settings = get_settings()
    emulator_host = os.environ["FIRESTORE_EMULATOR_HOST"]
    url = (
        f"http://{emulator_host}/emulator/v1/projects/"
        f"{settings.google_cloud_project}/databases/(default)/documents"
    )
    httpx.delete(url, timeout=10)


@pytest.fixture(autouse=True)
def _clean_firestore(db: firestore.Client):
    # Wipe before, not after, so state is clean at the start of every test
    # regardless of how the previous test ended (including a crash).
    _wipe_emulator(db)
    yield


@pytest.fixture
def client(db: firestore.Client):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_admin(db: firestore.Client):
    settings = get_settings()
    users = UsersRepository(db)
    return users.create(
        email=ADMIN_EMAIL,
        hashed_password=hash_password(ADMIN_PASSWORD, settings=settings),
        role=UserRole.ADMIN,
    )
