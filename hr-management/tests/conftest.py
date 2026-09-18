import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.core.config import get_settings
from app.core.dependencies import get_db
from app.core.firestore_client import get_firestore_client, reset_firestore_client
from app.core.security import hash_password
from app.main import create_app
from app.models import UserRole
from app.repositories.users_repository import UsersRepository

ADMIN_EMAIL = "admin@hr-management-test.dev"
ADMIN_PASSWORD = "CorrectHorse123!"
EMPLOYEE_EMAIL = "employee@hr-management-test.dev"
EMPLOYEE_PASSWORD = "CorrectHorse123!"

# Deliberately different from GOOGLE_CLOUD_PROJECT=hr-management-dev (the
# project `docker compose up`'s interactive dev server uses). _wipe_emulator
# below deletes every document in this project before each test — sharing
# the dev project would silently destroy real dev/demo data on every test
# run (this happened for real: every `pytest` run this session was wiping
# the admin account and demo data seeded for manual testing, and it looked
# exactly like an unrelated Docker/lockout issue from the outside).
_TEST_PROJECT = "hr-management-test"


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


@pytest.fixture(scope="session", autouse=True)
def _use_isolated_test_project(_require_emulator):
    os.environ["GOOGLE_CLOUD_PROJECT"] = _TEST_PROJECT
    get_settings.cache_clear()
    reset_firestore_client()


@pytest.fixture(scope="session")
def db(_use_isolated_test_project) -> firestore.Client:
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
def app(db: firestore.Client) -> FastAPI:
    """The FastAPI app instance, shared by every TestClient built in a
    test. dependency_overrides lives on the app object, not on any one
    TestClient, so every client built against this fixture — the plain
    `client` and every "logged in as X" client below — sees the same
    Firestore override without needing its own lifespan/startup run (the
    session-scoped `db` fixture already built the Firestore client before
    any of this runs).
    """
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded_admin(db: firestore.Client):
    settings = get_settings()
    users = UsersRepository(db)
    return users.create(
        email=ADMIN_EMAIL,
        hashed_password=hash_password(ADMIN_PASSWORD, settings=settings),
        role=UserRole.ADMIN,
    )


def _log_in(app: FastAPI, email: str, password: str) -> TestClient:
    """Builds a FRESH TestClient with its own cookie jar, logged in as the
    given user. Deliberately does NOT reuse/mutate another TestClient's
    cookies — two "logged in as X" clients built this way stay independent,
    which matters for any test needing two identities at once (e.g. an
    admin acting on an employee's request). All these clients still share
    the same `app` object (and therefore the same dependency_overrides), so
    they all see the same Firestore emulator data.
    """
    settings = get_settings()
    new_client = TestClient(app)
    login_response = new_client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )
    access_token = login_response.cookies.get(settings.cookie_name)
    new_client.cookies.set(settings.cookie_name, access_token)
    return new_client


@pytest.fixture
def admin_client(app: FastAPI, seeded_admin):
    return _log_in(app, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture
def employee_client(app: FastAPI, db: firestore.Client):
    settings = get_settings()
    users = UsersRepository(db)
    users.create(
        email=EMPLOYEE_EMAIL,
        hashed_password=hash_password(EMPLOYEE_PASSWORD, settings=settings),
        role=UserRole.EMPLOYEE,
    )
    return _log_in(app, EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD)


@pytest.fixture
def make_manager_client(app: FastAPI, db: firestore.Client):
    """Factory (not a fixed fixture) since a manager needs a caller-chosen
    department_id — module 11 (Settings > Utilisateurs) doesn't exist yet
    to do this through the app, so tests link the account directly via the
    repository, same technique as `make_employee_linked_client` below.
    Each call returns an independent client — see `_log_in`.
    """
    settings = get_settings()
    users = UsersRepository(db)

    def _make(
        department_id: str,
        email: str = "manager@hr-management-test.dev",
        password: str = "CorrectHorse123!",
    ) -> TestClient:
        users.create(
            email=email,
            hashed_password=hash_password(password, settings=settings),
            role=UserRole.MANAGER,
            department_id=department_id,
        )
        return _log_in(app, email, password)

    return _make


@pytest.fixture
def make_employee_linked_client(app: FastAPI, db: firestore.Client):
    """Factory for an EMPLOYEE-role login linked to a specific employee_id
    — there's no admin UI to do this yet (Module 11), so tests use the
    repository directly, same as the seed script does for the admin user.
    Each call returns an independent client — see `_log_in`.
    """
    settings = get_settings()
    users = UsersRepository(db)

    def _make(
        employee_id: str,
        email: str = "linked-employee@hr-management-test.dev",
        password: str = "CorrectHorse123!",
    ) -> TestClient:
        users.create(
            email=email,
            hashed_password=hash_password(password, settings=settings),
            role=UserRole.EMPLOYEE,
            employee_id=employee_id,
        )
        return _log_in(app, email, password)

    return _make
