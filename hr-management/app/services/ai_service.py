from __future__ import annotations

import io
import json
import re
from datetime import date

from docx import Document as DocxDocument
from email_validator import EmailNotValidError, validate_email
from google.cloud import firestore
from pypdf import PdfReader

from app.core.ai_client import AIClient
from app.core.ai_privacy import assert_no_sensitive_keys
from app.models import AIFunction, DashboardSnapshot, DraftRequest, DraftResponse, ExtractedCVFields
from app.repositories.ai_audit_log_repository import AIAuditLogRepository
from app.repositories.base import get_counter_value, increment_counter
from app.repositories.departments_repository import DepartmentsRepository
from app.repositories.positions_repository import PositionsRepository
from app.repositories.settings_repository import SettingsRepository

_PHONE_PATTERN = re.compile(r"^(?:\+212|0)[5-7]\d{8}$")
_PDF_CONTENT_TYPE = "application/pdf"
_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_CV_TEXT_CHAR_LIMIT = 8000  # keep the outbound prompt bounded

# The LLM sometimes wraps an otherwise-valid JSON reply in a markdown code
# fence (```json ... ```) despite being told to return "rien d'autre" —
# observed in practice with the longer CV-extraction prompt. json.loads()
# rejects that outright, so strip a wrapping fence before parsing rather
# than let a cosmetic formatting choice silently zero out every field.
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_json_fence(text: str) -> str:
    match = _JSON_FENCE_RE.match(text.strip())
    return match.group(1) if match else text

_CV_SYSTEM_PROMPT = (
    "Tu extrais des informations structurées à partir d'un texte de CV, pour "
    "aider un recruteur. Réponds uniquement avec un objet JSON valide (rien "
    "d'autre) contenant, si présentes dans le texte, les clés suivantes : "
    "first_name, last_name, professional_email, phone (normalisé sans espaces, "
    "points ni tirets — uniquement des chiffres, avec un éventuel préfixe "
    "+212, ex. \"0612345678\"), birth_date (format AAAA-MM-JJ). Omets toute "
    "clé dont l'information n'est pas présente dans le texte. N'invente "
    "aucune donnée.\n\n"
    "Ajoute aussi si possible :\n"
    '- "summary" : un résumé de 2 à 3 phrases en français du profil '
    "(expérience, compétences clés, points forts), pour une évaluation rapide.\n"
    '- "skills" : une liste de 5 à 10 compétences ou technologies courtes '
    "(mots ou courtes expressions, ex. \"Python\", \"Gestion de projet\"), "
    "réellement mentionnées dans le CV.\n"
    '- "suggested_contract_type" : uniquement si le texte l\'indique '
    "clairement (ex. \"recherche un stage\", \"contrat actuel : CDD\"), l'une "
    'de ces trois valeurs exactes : "CDI", "CDD", "STAGE". Sinon, omets cette clé.\n'
    '- "suggested_department_id" et "suggested_position_id" : la liste '
    '"available_positions" fournie énumère les départements et postes qui '
    "existent réellement dans le système, chacun avec son department_id et "
    "son position_id. Si le profil correspond clairement à l'un d'eux, "
    "renvoie ces identifiants exacts, tels quels. Sinon, omets ces deux clés. "
    "N'invente jamais un identifiant absent de la liste fournie."
)

_DRAFT_SYSTEM_PROMPTS = {
    "job_description": (
        "Tu rédiges une description de poste professionnelle en français, claire et concise."
    ),
    "internal_letter": "Tu rédiges un courrier interne professionnel en français.",
    "service_note": "Tu rédiges une note de service professionnelle en français.",
    "certificate_message": (
        "Tu rédiges un court message d'accompagnement professionnel en français, "
        "destiné à accompagner l'envoi d'une attestation."
    ),
}

_SUMMARY_SYSTEM_PROMPT = (
    "Tu es un assistant RH. À partir d'indicateurs agrégés (aucun nom de personne "
    "n'est fourni), rédige une courte synthèse commentée en français (deux ou trois "
    "phrases), en signalant les points notables (alertes, tendances). Réponds en "
    "texte brut uniquement : pas de markdown, pas d'astérisques, pas de titres, "
    "pas de listes à puces — seulement des phrases normales, le texte est affiché "
    "tel quel sans mise en forme."
)


class AIDisabledError(Exception):
    """The Assistant module is off — cahier des charges: "activation
    relève de l'administrateur," off by default."""


class AIQuotaExceededError(Exception):
    def __init__(self, scope: str):
        self.scope = scope  # "daily" or "monthly"
        super().__init__(f"AI {scope} quota exceeded")


class UnsupportedFileTypeError(Exception):
    def __init__(self, content_type: str):
        self.content_type = content_type
        super().__init__(f"Unsupported CV file type: {content_type}")


_STAFFING_OPTIONS_LIMIT = 100


class AIService:
    def __init__(
        self,
        ai_client: AIClient,
        audit_log_repository: AIAuditLogRepository,
        settings_repository: SettingsRepository,
        departments_repository: DepartmentsRepository,
        positions_repository: PositionsRepository,
        db: firestore.Client,
    ):
        self._client = ai_client
        self._audit_log = audit_log_repository
        self._settings = settings_repository
        self._departments_repository = departments_repository
        self._positions_repository = positions_repository
        self._db = db

    def _check_enabled_and_quota(self, user_id: str) -> None:
        settings = self._settings.get_ai()
        if settings is None or not settings.enabled:
            raise AIDisabledError()
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")
        if get_counter_value(self._db, f"ai_calls_{user_id}_{today}") >= settings.daily_quota_per_user:
            raise AIQuotaExceededError("daily")
        if get_counter_value(self._db, f"ai_calls_global_{month}") >= settings.monthly_quota_global:
            raise AIQuotaExceededError("monthly")

    def _record_usage(self, user_id: str, function: AIFunction) -> None:
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")
        increment_counter(self._db, f"ai_calls_{user_id}_{today}", delta=1)
        increment_counter(self._db, f"ai_calls_global_{month}", delta=1)
        self._audit_log.create(user_id=user_id, function=function)

    @staticmethod
    def _extract_text(file_bytes: bytes, content_type: str) -> str:
        if content_type == _PDF_CONTENT_TYPE:
            reader = PdfReader(io.BytesIO(file_bytes))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if content_type == _DOCX_CONTENT_TYPE:
            document = DocxDocument(io.BytesIO(file_bytes))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        raise UnsupportedFileTypeError(content_type)

    def _staffing_options(self) -> tuple[list[dict], set[str], dict[str, set[str]]]:
        """The real department/position list, so the model can only ever
        suggest something that actually exists — never invented, per the
        same "don't hallucinate data" rule as the extracted contact fields.
        """
        departments = self._departments_repository.list(
            cursor_id=None, limit=_STAFFING_OPTIONS_LIMIT
        )
        department_ids = {department.id for department in departments}
        positions_by_department: dict[str, set[str]] = {}
        options: list[dict] = []
        for department in departments:
            positions = self._positions_repository.list(
                department_id=department.id, cursor_id=None, limit=_STAFFING_OPTIONS_LIMIT
            )
            positions_by_department[department.id] = {position.id for position in positions}
            for position in positions:
                options.append(
                    {
                        "department_id": department.id,
                        "department_name": department.name,
                        "position_id": position.id,
                        "position_title": position.title,
                    }
                )
        return options, department_ids, positions_by_department

    def extract_cv(self, user_id: str, file_bytes: bytes, content_type: str) -> ExtractedCVFields:
        # Format validation is a pure input check — reject before touching
        # quota or the AI provider at all, per the plan's "rejects anything
        # else with a clear message before ever calling the model."
        text = self._extract_text(file_bytes, content_type)
        self._check_enabled_and_quota(user_id)

        options, department_ids, positions_by_department = self._staffing_options()
        payload = {"cv_text": text[:_CV_TEXT_CHAR_LIMIT], "available_positions": options}
        assert_no_sensitive_keys(payload)
        raw_response = self._client.complete(
            system=_CV_SYSTEM_PROMPT, user=json.dumps(payload), max_tokens=700
        )
        self._record_usage(user_id, AIFunction.CV_IMPORT)
        return _parse_extracted_fields(raw_response, department_ids, positions_by_department)

    def generate_draft(self, user_id: str, request: DraftRequest) -> DraftResponse:
        self._check_enabled_and_quota(user_id)
        payload = {"context": request.context}
        assert_no_sensitive_keys(payload)
        system = _DRAFT_SYSTEM_PROMPTS[request.draft_type]
        text = self._client.complete(system=system, user=request.context, max_tokens=800)
        self._record_usage(user_id, AIFunction.DRAFT)
        return DraftResponse(text=text)

    def summarize_dashboard(self, user_id: str, snapshot: DashboardSnapshot) -> str:
        self._check_enabled_and_quota(user_id)
        # Aggregates only — counts and department labels, never the
        # underlying EmployeeDocument/TrialPeriodDocument lists, so there
        # is no employee name in this payload to begin with. Satisfies
        # "aucun nom d'employé n'est transmis" by construction.
        payload = {
            "employees_active": snapshot.employees_active,
            "interns": snapshot.interns,
            "leaves_pending": snapshot.leaves_pending,
            "departments_active": snapshot.departments_active,
            "contracts_expiring_count": len(snapshot.contracts_expiring),
            "interns_ending_soon_count": len(snapshot.interns_ending_soon),
            "trial_periods_ending_soon_count": len(snapshot.trial_periods_ending_soon),
            "birthdays_this_month_count": len(snapshot.birthdays_this_month),
            "new_hires_this_month_count": len(snapshot.new_hires_this_month),
            "department_distribution": snapshot.department_distribution,
            "contract_type_distribution": snapshot.contract_type_distribution,
        }
        assert_no_sensitive_keys(payload)
        text = self._client.complete(
            system=_SUMMARY_SYSTEM_PROMPT, user=json.dumps(payload), max_tokens=400
        )
        self._record_usage(user_id, AIFunction.SUMMARY)
        return text


def _parse_extracted_fields(
    raw_response: str,
    valid_department_ids: set[str],
    positions_by_department: dict[str, set[str]],
) -> ExtractedCVFields:
    try:
        parsed = json.loads(_strip_json_fence(raw_response))
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    fields: dict = {}

    first_name = parsed.get("first_name")
    if isinstance(first_name, str) and first_name.strip():
        fields["first_name"] = first_name.strip()[:50]

    last_name = parsed.get("last_name")
    if isinstance(last_name, str) and last_name.strip():
        fields["last_name"] = last_name.strip()[:50]

    email = parsed.get("professional_email")
    if isinstance(email, str):
        try:
            fields["professional_email"] = validate_email(email, check_deliverability=False).normalized
        except EmailNotValidError:
            pass

    phone = parsed.get("phone")
    if isinstance(phone, str) and _PHONE_PATTERN.match(phone):
        fields["phone"] = phone

    birth_date_raw = parsed.get("birth_date")
    if isinstance(birth_date_raw, str):
        try:
            fields["birth_date"] = date.fromisoformat(birth_date_raw)
        except ValueError:
            pass

    summary = parsed.get("summary")
    if isinstance(summary, str) and summary.strip():
        fields["summary"] = summary.strip()[:500]

    skills_raw = parsed.get("skills")
    if isinstance(skills_raw, list):
        skills = [s.strip()[:50] for s in skills_raw if isinstance(s, str) and s.strip()]
        if skills:
            fields["skills"] = skills[:10]

    contract_type = parsed.get("suggested_contract_type")
    if isinstance(contract_type, str) and contract_type in {"CDI", "CDD", "STAGE"}:
        fields["suggested_contract_type"] = contract_type

    # A suggested position is only kept if it belongs to the suggested
    # department — a same-department requirement, not just "any real id",
    # so a hallucinated or mismatched pairing can't slip through as if it
    # were validated.
    department_id = parsed.get("suggested_department_id")
    if isinstance(department_id, str) and department_id in valid_department_ids:
        fields["suggested_department_id"] = department_id
        position_id = parsed.get("suggested_position_id")
        if isinstance(position_id, str) and position_id in positions_by_department.get(
            department_id, set()
        ):
            fields["suggested_position_id"] = position_id

    return ExtractedCVFields(**fields)
