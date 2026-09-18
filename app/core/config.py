from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "dev"
    app_name: str = "HR Management"

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Symmetric key for salary/RIB encryption (app.core.crypto). Required,
    # no default: per cahier des charges "Gestion de la clé de chiffrement",
    # this must never live in the codebase. Generate with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    fernet_key: str

    bcrypt_rounds: int = 12
    login_max_failed_attempts: int = 5
    login_lockout_minutes: int = 15

    google_cloud_project: str = "hr-management-dev"
    firestore_emulator_host: str | None = None
    firebase_auth_emulator_host: str | None = None
    firebase_storage_emulator_host: str | None = None

    cookie_name: str = "hr_access_token"
    refresh_cookie_name: str = "hr_refresh_token"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    # Not .local/.test/.example/.invalid: those are IANA special-use domains
    # that email-validator (backing pydantic's EmailStr) rejects outright,
    # even with deliverability/DNS checks disabled.
    seed_admin_email: str = "admin@hr-management.dev"
    seed_admin_password: str = "ChangeMe123!"

    # Module 12 (Assistant intelligent) — optional, unlike fernet_key/
    # jwt_secret_key: the module is disabled by default ("Le module est
    # désactivé par défaut") and the app must run fully without a key set.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
