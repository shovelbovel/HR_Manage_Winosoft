from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    """Only ADMIN and EMPLOYEE exist in the scaffold. MANAGER is added when
    Module 4 (Départements) and department-scoped queries land, since it has
    no meaning without a department to be scoped to."""

    ADMIN = "admin"
    EMPLOYEE = "employee"


class UserDocument(BaseModel):
    """Shape of a document in the `users` Firestore collection.

    Format/shape validation only — no logic depending on request context,
    per the cahier des charges' "models.py" layer rule.
    """

    id: str
    employee_id: str | None = None
    email: EmailStr
    hashed_password: str
    role: UserRole
    is_active: bool = True
    search_tokens: list[str] = Field(default_factory=list)
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    last_login: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPayload(BaseModel):
    sub: str
    role: UserRole | None = None
    employee_id: str | None = None
    token_type: Literal["access", "refresh"]
    exp: int


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class CurrentUser(BaseModel):
    """The authenticated caller, as resolved by app.core.dependencies.get_current_user
    for the duration of a single request. Distinct from UserDocument: this is
    the identity the rest of the request-handling code reasons about, not a
    raw Firestore document."""

    id: str
    email: EmailStr
    role: UserRole
    employee_id: str | None = None
