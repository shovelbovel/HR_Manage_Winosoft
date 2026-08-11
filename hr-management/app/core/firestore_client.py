import os

from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from app.core.config import Settings, get_settings

_client: firestore.Client | None = None


def _configure_emulator_env(settings: Settings) -> None:
    """Mirror the emulator host settings into os.environ.

    pydantic-settings loading .env only populates the Settings object, it
    never writes into os.environ. But google-cloud-firestore reads
    FIRESTORE_EMULATOR_HOST straight from os.environ to decide whether to
    route to the emulator. Without this, a local `uv run` outside Docker
    (where compose's `environment:` block hasn't already exported the var)
    would silently try to reach production Firestore with no credentials
    instead of the emulator.
    """
    if settings.firestore_emulator_host:
        os.environ.setdefault("FIRESTORE_EMULATOR_HOST", settings.firestore_emulator_host)
    if settings.firebase_auth_emulator_host:
        os.environ.setdefault("FIREBASE_AUTH_EMULATOR_HOST", settings.firebase_auth_emulator_host)
    if settings.firebase_storage_emulator_host:
        os.environ.setdefault(
            "FIREBASE_STORAGE_EMULATOR_HOST", settings.firebase_storage_emulator_host
        )


def get_firestore_client() -> firestore.Client:
    """Return a process-wide Firestore client singleton.

    Built via google.cloud.firestore.Client rather than
    firebase_admin.firestore.client(): a firebase_admin App always resolves
    real Application Default Credentials before handing off to the
    underlying Firestore client, which fails hard with no GCP credentials
    configured. google.cloud.firestore.Client auto-substitutes
    AnonymousCredentials() when FIRESTORE_EMULATOR_HOST is set and no
    credentials are passed, so it works against the emulator with zero
    setup. When a real Firebase project is wired in later, swap this for
    firebase_admin-issued credentials (a service account key) and drop the
    AnonymousCredentials branch.
    """
    global _client
    if _client is not None:
        return _client

    settings = get_settings()
    _configure_emulator_env(settings)

    if settings.firestore_emulator_host:
        _client = firestore.Client(
            project=settings.google_cloud_project,
            credentials=AnonymousCredentials(),
        )
    else:
        _client = firestore.Client(project=settings.google_cloud_project)

    return _client


def reset_firestore_client() -> None:
    """Drop the cached client so a new one is built on next access.

    Used by tests to point the client at a fresh/test project.
    """
    global _client
    _client = None
