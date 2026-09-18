from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, computed_field, field_validator, model_validator


class UserRole(str, Enum):
    """MANAGER added in Module 6 (Congés): department-scoped approval is the
    first place a manager's own department (UserDocument.department_id)
    actually gates a query."""

    ADMIN = "admin"
    MANAGER = "manager"
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
    # Denormalized, per the cahier des charges' users table: "sert au
    # cloisonnement du manager sans lecture supplémentaire." Only
    # meaningful for MANAGER accounts.
    department_id: str | None = None
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
    department_id: str | None = None


class DepartmentDocument(BaseModel):
    """Shape of a document in the `departments` Firestore collection.

    The cahier des charges gives no explicit field table for this
    collection (unlike users/employees) — fields are kept to the minimum
    the stated business rules require: an immutable unique code, a name,
    and a service-maintained employee count.
    """

    id: str
    code: str
    name: str
    employee_count: int = 0
    created_at: datetime
    updated_at: datetime


class DepartmentCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=10, pattern=r"^[A-Z0-9-]+$")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("code", mode="before")
    @classmethod
    def _normalize_code(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class DepartmentUpdateRequest(BaseModel):
    """No `code` field: this is how "le code du département est immuable
    après création" is enforced — there is no code path that can write a
    new code value after creation, not a runtime check."""

    name: str = Field(min_length=1, max_length=100)


class PositionDocument(BaseModel):
    """Shape of a document in the `positions` Firestore collection.

    No unique-code field, unlike departments — the cahier des charges states
    no uniqueness requirement for positions.
    """

    id: str
    department_id: str
    department_name: str
    title: str
    max_occupants: int | None = None
    occupant_count: int = 0
    created_at: datetime
    updated_at: datetime


def _blank_to_none(value: object) -> object:
    # An HTML number input left empty submits "" rather than omitting the
    # field entirely, which would otherwise fail int-or-None coercion.
    return None if value == "" else value


class PositionCreateRequest(BaseModel):
    department_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=100)
    max_occupants: int | None = Field(default=None, gt=0)

    _normalize_max_occupants = field_validator("max_occupants", mode="before")(_blank_to_none)


class PositionUpdateRequest(BaseModel):
    """No `department_id` field: a position's department is immutable after
    creation, same trick as DepartmentUpdateRequest's missing `code`."""

    title: str = Field(min_length=1, max_length=100)
    max_occupants: int | None = Field(default=None, gt=0)

    _normalize_max_occupants = field_validator("max_occupants", mode="before")(_blank_to_none)


class EmployeeStatus(str, Enum):
    """Default TRIAL per the v2.0-carried field. Automatic TRIAL->ACTIVE and
    ->EXPIRED transitions need a scheduled task (Module 8/Cloud Functions,
    not built) — status changes are manual (activate/deactivate) until then.
    """

    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    INACTIVE = "inactive"


class ContractType(str, Enum):
    CDI = "CDI"
    CDD = "CDD"
    STAGE = "STAGE"


class ContractCategory(str, Enum):
    """Only meaningful for CDI — the cahier des charges' trial-period
    duration table (Module 8) is keyed by category for CDI, and doesn't
    distinguish categories for CDD/Stage."""

    CADRE = "CADRE"
    EMPLOYEE = "EMPLOYEE"
    OUVRIER = "OUVRIER"


_CIN_PATTERN = r"^[A-Z]{1,2}[0-9]{5,6}$"
_PHONE_PATTERN = r"^(?:\+212|0)[5-7]\d{8}$"
_RIB_PATTERN = r"^\d{24}$"
_MINIMUM_AGE_YEARS = 16


class EmployeeDocument(BaseModel):
    """Shape of a document in the `employees` Firestore collection. Every
    field is grounded in specific cahier des charges text — see the Module 3
    implementation plan for the citation of each. Salary/RIB are Fernet
    ciphertext (app.core.crypto), never plaintext at this layer.
    """

    id: str
    matricule: str
    first_name: str
    last_name: str
    cin: str
    birth_date: datetime
    birth_month: int
    professional_email: EmailStr
    phone: str
    department_id: str
    department_name: str
    position_id: str
    position_title: str
    hire_date: datetime
    contract_type: ContractType
    contract_category: ContractCategory | None = None
    contract_start_date: datetime
    contract_end_date: datetime | None = None
    status: EmployeeStatus = EmployeeStatus.TRIAL
    gross_salary_encrypted: str
    rib_encrypted: str
    cnss_number: str
    emergency_contact_name: str
    emergency_contact_phone: str
    internal_notes: str | None = None
    search_tokens: list[str] = Field(default_factory=list)
    photo_url: str | None = None
    created_at: datetime
    updated_at: datetime


class _EmployeePersonalAndContractFields(BaseModel):
    """Shared shape for create/update requests — everything except the
    department_id/position_id assignment, which create-only exposes (see
    EmployeeCreateRequest's docstring for why update doesn't).
    """

    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    cin: str = Field(pattern=_CIN_PATTERN)
    birth_date: date
    professional_email: EmailStr
    phone: str = Field(pattern=_PHONE_PATTERN)
    hire_date: date
    contract_type: ContractType
    contract_category: ContractCategory | None = None
    contract_start_date: date
    contract_end_date: date | None = None
    gross_salary: float = Field(gt=0)
    rib: str = Field(pattern=_RIB_PATTERN)
    cnss_number: str = Field(min_length=1, max_length=20)
    emergency_contact_name: str = Field(min_length=1, max_length=100)
    emergency_contact_phone: str = Field(pattern=_PHONE_PATTERN)
    internal_notes: str | None = None

    _normalize_contract_end_date = field_validator("contract_end_date", mode="before")(
        _blank_to_none
    )
    _normalize_internal_notes = field_validator("internal_notes", mode="before")(_blank_to_none)

    @field_validator("cin", mode="before")
    @classmethod
    def _normalize_cin(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("birth_date")
    @classmethod
    def _check_minimum_age(cls, value: date) -> date:
        today = date.today()
        try:
            cutoff = today.replace(year=today.year - _MINIMUM_AGE_YEARS)
        except ValueError:
            # today is Feb 29 and (today.year - 16) isn't a leap year.
            cutoff = today.replace(year=today.year - _MINIMUM_AGE_YEARS, day=28)
        if value > cutoff:
            raise ValueError(
                f"L'employé doit avoir au moins {_MINIMUM_AGE_YEARS} ans "
                "(Code du travail, article 143)."
            )
        return value

    @model_validator(mode="after")
    def _check_contract_dates(self) -> "_EmployeePersonalAndContractFields":
        if self.contract_end_date is not None and self.contract_end_date < self.contract_start_date:
            raise ValueError("La date de fin de contrat doit être postérieure à la date de début.")
        return self

    @model_validator(mode="after")
    def _check_contract_category_and_end_date(self) -> "_EmployeePersonalAndContractFields":
        # contract_category only means something for CDI (Module 8's trial
        # duration table is keyed by it for CDI only) — required there,
        # cleared everywhere else rather than left as whatever was
        # submitted, so a stale value can't linger after a contract-type
        # change.
        if self.contract_type == ContractType.CDI:
            if self.contract_category is None:
                raise ValueError("La catégorie (Cadre/Employé/Ouvrier) est requise pour un CDI.")
        else:
            self.contract_category = None

        # A CDD's trial-period duration (Module 8) is computed from the
        # contract's length, so it must have an end date.
        if self.contract_type == ContractType.CDD and self.contract_end_date is None:
            raise ValueError("La date de fin de contrat est requise pour un CDD.")
        return self


class EmployeeCreateRequest(_EmployeePersonalAndContractFields):
    department_id: str = Field(min_length=1)
    position_id: str = Field(min_length=1)
    # Stage trial periods have no formula ("selon convention" — cahier des
    # charges Module 8) — required only for STAGE, since a trial period
    # must exist for every employee and there's no way to compute one here.
    trial_end_date_override: date | None = None

    _normalize_trial_end_date_override = field_validator(
        "trial_end_date_override", mode="before"
    )(_blank_to_none)

    @model_validator(mode="after")
    def _check_trial_end_date_override(self) -> "EmployeeCreateRequest":
        if self.contract_type == ContractType.STAGE and self.trial_end_date_override is None:
            raise ValueError(
                "La date de fin de période d'essai est requise pour un stage "
                "(durée fixée par convention)."
            )
        if self.contract_type != ContractType.STAGE:
            self.trial_end_date_override = None
        return self


class EmployeeUpdateRequest(_EmployeePersonalAndContractFields):
    """No `department_id`/`position_id`: reassigning department or position
    affects occupancy counters and capacity checks, so it's a distinct
    operation from a plain field edit — not supported by this endpoint in
    this task (documented gap, not silently dropped)."""


class LeaveTypeDocument(BaseModel):
    """Shape of a document in the `leave_types` collection. Seed-only in
    this pass (scripts/seed.py) — Module 11 (Settings > Congés) will add
    admin CRUD for this later."""

    id: str
    code: str
    name: str
    default_days_per_year: int | None = None
    is_deductible: bool
    requires_justification: bool
    created_at: datetime
    updated_at: datetime


class HolidayDocument(BaseModel):
    """Shape of a document in the `holidays` collection. Fixed grégorien
    dates are seeded by scripts/seed.py as recurring; lunar/religious
    holidays (cahier des charges' "Réserve sur les jours fériés
    religieux") are entered manually, once per year, via
    Settings > Congés, hence `year` — meaningless for a recurring entry,
    required for a non-recurring one.
    """

    id: str
    name: str
    is_recurring: bool
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    year: int | None = None


class LeaveBalanceDocument(BaseModel):
    """Shape of a document in the `leave_balances` collection. Identifier is
    deterministic: {employee_id}_{leave_type_id}_{year} — this replaces
    UNIQUE(employee_id, leave_type_id, year), a duplicate becomes impossible
    by construction. No `remaining` field: computed at read time
    (initial + accrued - used), per the cahier des charges' "un champ
    dérivé persistant finit toujours par diverger de ses composantes."
    """

    id: str
    employee_id: str
    leave_type_id: str
    year: int
    initial: int = 0
    accrued: int = 0
    used: int = 0
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def remaining(self) -> int:
        return self.initial + self.accrued - self.used


class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LeaveDocument(BaseModel):
    """Shape of a document in the `leaves` collection."""

    id: str
    employee_id: str
    employee_name: str
    department_id: str
    leave_type_id: str
    leave_type_name: str
    start_date: datetime
    end_date: datetime
    working_days: int
    status: LeaveStatus = LeaveStatus.PENDING
    reason: str | None = None
    rejection_reason: str | None = None
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None
    created_at: datetime
    updated_at: datetime


class LeaveCreateRequest(BaseModel):
    leave_type_id: str = Field(min_length=1)
    start_date: date
    end_date: date
    reason: str | None = None

    _normalize_reason = field_validator("reason", mode="before")(_blank_to_none)

    @model_validator(mode="after")
    def _check_dates(self) -> "LeaveCreateRequest":
        if self.end_date < self.start_date:
            raise ValueError("La date de fin doit être postérieure à la date de début.")
        return self


class LeaveRejectRequest(BaseModel):
    """`reason` is mandatory here (unlike LeaveDocument.rejection_reason,
    which is nullable at rest for pending/approved requests) — the cahier
    des charges requires a motif to refuse a request."""

    reason: str = Field(min_length=1, max_length=500)


class TrialPeriodStatus(str, Enum):
    PENDING = "pending"
    EXTENDED = "extended"
    VALIDATED = "validated"
    REFUSED = "refused"


class TrialPeriodDocument(BaseModel):
    """Shape of a document in the `trial_periods` collection. The id is
    always the owning employee's id (deterministic, mirrors
    leave_balances) — "aucun employé ne peut exister sans période d'essai
    associée" becomes a single lookup by employee_id rather than a query.
    """

    id: str
    employee_id: str
    contract_type: ContractType
    contract_category: ContractCategory | None = None
    start_date: datetime
    initial_end_date: datetime
    extended_end_date: datetime | None = None
    status: TrialPeriodStatus = TrialPeriodStatus.PENDING
    decision_reason: str | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def effective_end_date(self) -> datetime:
        return self.extended_end_date or self.initial_end_date


class TrialPeriodDecisionRequest(BaseModel):
    """Used for all three trial-period actions (validate/extend/refuse) —
    the cahier des charges requires a motif for every one of them:
    "valider, prolonger ou refuser, avec motif et traçabilité."
    """

    reason: str = Field(min_length=1, max_length=500)


class DashboardSnapshot(BaseModel):
    """Assembled by app.services.dashboard_service — not a Firestore
    document, the response shape for the Module 2 dashboard. Same
    non-document-shape treatment as CurrentUser.
    """

    employees_active: int
    interns: int
    leaves_pending: int
    departments_active: int | None  # None for a manager — not department-scoped
    contracts_expiring: list[EmployeeDocument]
    interns_ending_soon: list[EmployeeDocument]
    trial_periods_ending_soon: list[TrialPeriodDocument]
    birthdays_this_month: list[EmployeeDocument]
    new_hires_this_month: list[EmployeeDocument]
    department_distribution: list[tuple[str, int]]
    contract_type_distribution: dict[str, int]


class HomeBalanceSummary(BaseModel):
    leave_type_name: str
    remaining: int


class HomeSnapshot(BaseModel):
    """Assembled by app.services.home_service for the Employee's
    simplified `/home` page (cahier des charges: "page d'accueil avec
    solde de congés et informations rapides") — deliberately not a
    cut-down DashboardSnapshot.
    """

    has_employee_profile: bool
    balances: list[HomeBalanceSummary]
    recent_leaves: list[LeaveDocument]


class NotificationCategory(str, Enum):
    """The 8 categories from the cahier des charges' Module 9 table. Only
    LEAVE_PENDING/LEAVE_DECISION/NEW_EMPLOYEE are produced today (event-
    driven, fired from an existing service call site); the other five need
    a scheduled task (Cloud Functions/Scheduler) that doesn't exist in this
    project — see the Module 9 implementation plan's scope-decision note.
    """

    CONTRACT_EXPIRING = "contract_expiring"
    INTERNSHIP_ENDING = "internship_ending"
    TRIAL_PERIOD = "trial_period"
    LEAVE_PENDING = "leave_pending"
    LEAVE_DECISION = "leave_decision"
    BIRTHDAY = "birthday"
    MISSING_DOCUMENTS = "missing_documents"
    NEW_EMPLOYEE = "new_employee"


class NotificationDocument(BaseModel):
    """Shape of a document in the `notifications` collection — "Alertes par
    destinataire": one document per recipient, never a shared/broadcast row.
    """

    id: str
    recipient_user_id: str
    category: NotificationCategory
    message: str
    link: str | None = None
    is_read: bool = False
    created_at: datetime


class NotificationRecentResponse(BaseModel):
    """Response shape for GET /notifications/recent, the navbar bell's AJAX
    endpoint — bundles the badge count with the dropdown's 10 items so one
    fetch populates both."""

    unread_count: int
    notifications: list[NotificationDocument]


class CompanySettings(BaseModel):
    """Shape of the `settings/company` document — a thin Module 11 slice
    pulled forward as Module 7's prerequisite (the attestation header
    needs it), same as Postes was pulled forward for Employees. Document
    id is always the literal "company", per the cahier des charges'
    settings convention ("l'identifiant du document est la clé du
    paramètre").
    """

    id: str = "company"
    name: str = ""
    address: str = ""
    ice: str = ""
    rc: str = ""
    if_number: str = ""
    updated_at: datetime


class CompanySettingsUpdateRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    address: str = Field(default="", max_length=300)
    ice: str = Field(default="", max_length=50)
    rc: str = Field(default="", max_length=50)
    if_number: str = Field(default="", max_length=50)


class CertificateType(str, Enum):
    WORK = "work"  # Attestation de travail
    INTERNSHIP = "internship"  # Attestation de stage
    LEAVE = "leave"  # Attestation de congé
    SALARY = "salary"  # Attestation de salaire
    END_OF_CONTRACT = "end_of_contract"  # Certificat de fin de contrat


class CertificateDocument(BaseModel):
    """Shape of a document in the `certificates` collection. `data_snapshot`
    is deliberately a plain dict, not a typed sub-model — it's the frozen
    JSON the cahier des charges calls for ("les données utilisées sont
    figées en JSON"), shaped differently per certificate_type, and is
    never queried on — only ever rendered back into the PDF template.
    """

    id: str
    number: str  # ATT-AAAA-XXXX
    certificate_type: CertificateType
    employee_id: str
    department_id: str
    generated_by: str
    data_snapshot: dict
    created_at: datetime


class CertificateGenerateRequest(BaseModel):
    """`internship_subject`/`net_salary`/`leave_id` are certificate-specific
    one-off inputs, not employee attributes — see the Module 7 plan's
    scope-decision note on why they aren't fields on EmployeeDocument.
    """

    certificate_type: CertificateType
    employee_id: str = Field(min_length=1)
    internship_subject: str | None = Field(default=None, max_length=200)
    net_salary: float | None = Field(default=None, gt=0)
    leave_id: str | None = None

    _normalize_internship_subject = field_validator("internship_subject", mode="before")(
        _blank_to_none
    )

    @model_validator(mode="after")
    def _check_type_specific_fields(self) -> "CertificateGenerateRequest":
        if self.certificate_type == CertificateType.INTERNSHIP and not self.internship_subject:
            raise ValueError("Le sujet du stage est requis pour ce type d'attestation.")
        if self.certificate_type == CertificateType.SALARY and self.net_salary is None:
            raise ValueError("Le salaire net est requis pour ce type d'attestation.")
        if self.certificate_type == CertificateType.LEAVE and not self.leave_id:
            raise ValueError("Le congé à certifier est requis pour ce type d'attestation.")
        return self


def _check_password_complexity(value: str) -> str:
    # Module 1's stated policy ("huit caractères minimum, au moins une
    # majuscule, une minuscule et un chiffre") was never enforced in code
    # until Module 11's Utilisateurs screen — every account before this
    # was created via scripts/seed.py or a test fixture calling
    # UsersRepository.create() directly with an already-hashed password.
    if not any(c.isupper() for c in value):
        raise ValueError("Le mot de passe doit contenir au moins une majuscule.")
    if not any(c.islower() for c in value):
        raise ValueError("Le mot de passe doit contenir au moins une minuscule.")
    if not any(c.isdigit() for c in value):
        raise ValueError("Le mot de passe doit contenir au moins un chiffre.")
    return value


class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: UserRole
    employee_id: str | None = None
    department_id: str | None = None

    _check_password = field_validator("password")(_check_password_complexity)
    _normalize_employee_id = field_validator("employee_id", mode="before")(_blank_to_none)
    _normalize_department_id = field_validator("department_id", mode="before")(_blank_to_none)

    @model_validator(mode="after")
    def _check_role_specific_fields(self) -> "UserCreateRequest":
        if self.role == UserRole.MANAGER and not self.department_id:
            raise ValueError("Un manager doit être rattaché à un département.")
        if self.role != UserRole.MANAGER:
            self.department_id = None
        if self.role != UserRole.EMPLOYEE:
            self.employee_id = None
        return self


class UserPasswordResetRequest(BaseModel):
    password: str = Field(min_length=8)

    _check_password = field_validator("password")(_check_password_complexity)


class LeaveTypeCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=20, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=100)
    default_days_per_year: int | None = Field(default=None, ge=0)
    # Default False, not required: an unchecked HTML checkbox submits no
    # key at all (not a falsy value), so an absent key must mean "false."
    is_deductible: bool = False
    requires_justification: bool = False


class LeaveTypeUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    default_days_per_year: int | None = Field(default=None, ge=0)
    is_deductible: bool = False
    requires_justification: bool = False


class HolidayCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_recurring: bool = False
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    year: int | None = None

    @model_validator(mode="after")
    def _check_year(self) -> "HolidayCreateRequest":
        if not self.is_recurring and self.year is None:
            raise ValueError("L'année est requise pour un jour férié non récurrent.")
        if self.is_recurring:
            self.year = None
        return self


class AISettings(BaseModel):
    """Shape of the `settings/assistant` document. Disabled by default —
    cahier des charges Module 12: "Le module est désactivé par défaut."
    """

    id: str = "assistant"
    enabled: bool = False
    daily_quota_per_user: int = 20
    monthly_quota_global: int = 500


class AISettingsUpdateRequest(BaseModel):
    enabled: bool = False
    daily_quota_per_user: int = Field(default=20, ge=1)
    monthly_quota_global: int = Field(default=500, ge=1)


class AIFunction(str, Enum):
    CV_IMPORT = "cv_import"
    DRAFT = "draft"
    SUMMARY = "summary"


class AIAuditLogEntry(BaseModel):
    """Shape of a document in the `ai_audit_log` collection — "chaque
    appel est enregistré... avec l'auteur, la fonction utilisée,
    l'horodatage et le volume traité. Le contenu transmis n'est pas
    journalisé": deliberately no field carries the prompt or response.
    """

    id: str
    user_id: str
    function: AIFunction
    created_at: datetime


class ExtractedCVFields(BaseModel):
    """Fields the Assistant may pre-fill on the employee creation form
    from a parsed CV. Every field is optional and independently
    validated by app.services.ai_service — an individual malformed value
    (e.g. an unparsable date) is dropped from the response rather than
    failing the whole import, per the cahier des charges: "un CIN au
    mauvais format... est rejeté exactement comme s'il avait été tapé au
    clavier," not the whole submission.
    """

    first_name: str | None = None
    last_name: str | None = None
    professional_email: EmailStr | None = None
    phone: str | None = None
    birth_date: date | None = None
    # Added value beyond raw field extraction: a short human-readable
    # profile summary, and a department/position suggestion grounded in
    # this deployment's actual org structure (never invented — the service
    # validates the suggested ids against the real list before returning
    # them, dropping anything that doesn't match a real department/position
    # exactly the same way a malformed extracted field is dropped above).
    summary: str | None = None
    suggested_department_id: str | None = None
    suggested_position_id: str | None = None
    # Skills are free-text keywords (not validated against any fixed list —
    # there isn't one in this system), shown as informational tags only,
    # never written to the employee record (no such field exists on
    # EmployeeDocument). suggested_contract_type is grounded the same way
    # as the department/position suggestion: dropped unless it's exactly
    # one of the three real ContractType values, never invented.
    skills: list[str] | None = None
    suggested_contract_type: ContractType | None = None


class DraftRequest(BaseModel):
    draft_type: Literal["job_description", "internal_letter", "service_note", "certificate_message"]
    context: str = Field(min_length=1, max_length=2000)


class DraftResponse(BaseModel):
    text: str


class SummaryResponse(BaseModel):
    text: str
