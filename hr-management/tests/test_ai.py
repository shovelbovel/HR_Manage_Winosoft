import io
import json

import pytest
from docx import Document

from app.core.ai_client import AIServiceUnavailableError
from app.core.ai_privacy import SensitiveDataError, assert_no_sensitive_keys
from app.core.dependencies import get_ai_client
from app.core.pdf import render_html_to_pdf

JSON_HEADERS = {"accept": "application/json"}

_UNIQUE_COUNTER = {"value": 0}


class FakeAIClient:
    def __init__(self, response_text: str = "{}", raise_error: bool = False):
        self.calls: list[dict] = []
        self.response_text = response_text
        self.raise_error = raise_error

    def complete(self, *, system: str, user: str, max_tokens: int = 1024) -> str:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if self.raise_error:
            raise AIServiceUnavailableError("boom")
        return self.response_text


@pytest.fixture
def fake_ai_client(app):
    fake = FakeAIClient()
    app.dependency_overrides[get_ai_client] = lambda: fake
    yield fake
    del app.dependency_overrides[get_ai_client]


def _enable_ai(admin_client, daily_quota=20, monthly_quota=500):
    response = admin_client.post(
        "/settings/ai",
        json={
            "enabled": True,
            "daily_quota_per_user": daily_quota,
            "monthly_quota_global": monthly_quota,
        },
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200, response.text


def _create_department(client, code: str, name: str) -> str:
    response = client.post("/departments", json={"code": code, "name": name}, headers=JSON_HEADERS)
    return response.json()["id"]


def _create_position(client, department_id: str, title: str) -> str:
    response = client.post(
        "/positions", json={"department_id": department_id, "title": title}, headers=JSON_HEADERS
    )
    return response.json()["id"]


def _create_employee(client, department_id: str, position_id: str, **overrides) -> dict:
    _UNIQUE_COUNTER["value"] += 1
    n = _UNIQUE_COUNTER["value"]
    payload = {
        "first_name": "Karim",
        "last_name": "Secretissimo",
        "cin": f"AB{600000 + n}",
        "birth_date": "1990-05-15",
        "professional_email": f"ai-employee{n}@hr-management-test.dev",
        "phone": "0612345678",
        "department_id": department_id,
        "position_id": position_id,
        "hire_date": "2024-01-01",
        "contract_type": "CDI",
        "contract_category": "EMPLOYEE",
        "contract_start_date": "2024-01-01",
        "gross_salary": 8000,
        "rib": "1" * 24,
        "cnss_number": "1234567",
        "emergency_contact_name": "Marie Dupont",
        "emergency_contact_phone": "0612345679",
    }
    payload.update(overrides)
    response = client.post("/employees", json=payload, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _pdf_bytes(text: str) -> bytes:
    return render_html_to_pdf(f"<p>{text}</p>")


def _docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# -- Privacy filter (pure unit tests) ----------------------------------------


def test_assert_no_sensitive_keys_raises_for_forbidden_field():
    with pytest.raises(SensitiveDataError):
        assert_no_sensitive_keys({"gross_salary_encrypted": "abc"})


def test_assert_no_sensitive_keys_raises_for_nested_forbidden_field():
    with pytest.raises(SensitiveDataError):
        assert_no_sensitive_keys({"employee": {"cin": "AB123456"}})


def test_assert_no_sensitive_keys_allows_clean_payload():
    assert_no_sensitive_keys({"employees_active": 5, "department_distribution": [["IT", 3]]})


# -- Activation & quotas ------------------------------------------------------


def test_ai_disabled_by_default_blocks_draft_generation(admin_client, fake_ai_client):
    response = admin_client.post(
        "/ai/draft",
        json={"draft_type": "job_description", "context": "Développeur backend"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 403
    assert fake_ai_client.calls == []


def test_enabling_allows_draft_generation(admin_client, fake_ai_client):
    fake_ai_client.response_text = "Voici un brouillon de description de poste."
    _enable_ai(admin_client)

    response = admin_client.post(
        "/ai/draft",
        json={"draft_type": "job_description", "context": "Développeur backend"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "Voici un brouillon de description de poste."
    assert len(fake_ai_client.calls) == 1


def test_daily_quota_blocks_after_limit_reached(admin_client, fake_ai_client):
    _enable_ai(admin_client, daily_quota=1)

    first = admin_client.post(
        "/ai/draft",
        json={"draft_type": "service_note", "context": "Rappel des horaires"},
        headers=JSON_HEADERS,
    )
    assert first.status_code == 200

    second = admin_client.post(
        "/ai/draft",
        json={"draft_type": "service_note", "context": "Rappel des horaires"},
        headers=JSON_HEADERS,
    )
    assert second.status_code == 429


def test_ai_service_unavailable_returns_503(admin_client, fake_ai_client):
    _enable_ai(admin_client)
    fake_ai_client.raise_error = True

    response = admin_client.post(
        "/ai/draft",
        json={"draft_type": "internal_letter", "context": "Annonce interne"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 503


def test_draft_rejects_employee_role(employee_client, admin_client, fake_ai_client):
    _enable_ai(admin_client)
    response = employee_client.post(
        "/ai/draft",
        json={"draft_type": "internal_letter", "context": "Annonce"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 403


def test_draft_allowed_for_manager(admin_client, make_manager_client, fake_ai_client):
    fake_ai_client.response_text = "Brouillon manager."
    _enable_ai(admin_client)
    department_id = _create_department(admin_client, "AIMGR", "Dept AI Manager")
    manager = make_manager_client(department_id, email="ai-manager@hr-management-test.dev")

    response = manager.post(
        "/ai/draft",
        json={"draft_type": "service_note", "context": "Note pour l'équipe"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200, response.text


# -- CV import ----------------------------------------------------------------


def test_import_cv_pdf_extracts_and_validates_fields(admin_client, fake_ai_client):
    fake_ai_client.response_text = json.dumps(
        {
            "first_name": "Jean",
            "last_name": "Dupont",
            "professional_email": "jean.dupont@example.com",
            "phone": "0612345678",
            "birth_date": "1990-05-15",
        }
    )
    _enable_ai(admin_client)

    files = {"file": ("cv.pdf", _pdf_bytes("Jean Dupont — Développeur"), "application/pdf")}
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] == "Jean"
    assert body["last_name"] == "Dupont"
    assert body["professional_email"] == "jean.dupont@example.com"
    assert body["phone"] == "0612345678"
    assert body["birth_date"] == "1990-05-15"


def test_import_cv_docx_supported(admin_client, fake_ai_client):
    fake_ai_client.response_text = json.dumps({"first_name": "Sara"})
    _enable_ai(admin_client)

    files = {
        "file": (
            "cv.docx",
            _docx_bytes("Sara Idrissi"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["first_name"] == "Sara"


def test_import_cv_parses_response_wrapped_in_markdown_fence(admin_client, fake_ai_client):
    # Real LLM responses have been observed wrapping otherwise-valid JSON
    # in a ```json ... ``` fence despite the prompt saying not to — this
    # must not silently zero out every field.
    fake_ai_client.response_text = '```json\n{"first_name": "Jean"}\n```'
    _enable_ai(admin_client)

    files = {"file": ("cv.pdf", _pdf_bytes("Jean"), "application/pdf")}
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["first_name"] == "Jean"


def test_import_cv_drops_malformed_field_without_failing(admin_client, fake_ai_client):
    fake_ai_client.response_text = json.dumps(
        {"first_name": "Jean", "phone": "not-a-phone-number"}
    )
    _enable_ai(admin_client)

    files = {"file": ("cv.pdf", _pdf_bytes("Jean"), "application/pdf")}
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] == "Jean"
    assert body["phone"] is None


def test_import_cv_includes_summary_and_valid_department_position_suggestion(
    admin_client, fake_ai_client
):
    department_id = _create_department(admin_client, "AICV", "Dept AI CV")
    position_id = _create_position(admin_client, department_id, "Poste AI CV")
    fake_ai_client.response_text = json.dumps(
        {
            "first_name": "Jean",
            "summary": "Développeur avec 5 ans d'expérience en Python.",
            "suggested_department_id": department_id,
            "suggested_position_id": position_id,
        }
    )
    _enable_ai(admin_client)

    files = {"file": ("cv.pdf", _pdf_bytes("Jean Dupont — Développeur Python"), "application/pdf")}
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == "Développeur avec 5 ans d'expérience en Python."
    assert body["suggested_department_id"] == department_id
    assert body["suggested_position_id"] == position_id

    # The model was actually given the real department/position list to
    # choose from — not asked to invent one.
    sent_payload = fake_ai_client.calls[-1]["user"]
    assert department_id in sent_payload
    assert "Dept AI CV" in sent_payload


def test_import_cv_includes_skills_and_valid_contract_type_suggestion(
    admin_client, fake_ai_client
):
    fake_ai_client.response_text = json.dumps(
        {
            "first_name": "Jean",
            "skills": ["Python", "FastAPI", "PostgreSQL", ""],
            "suggested_contract_type": "CDD",
        }
    )
    _enable_ai(admin_client)

    files = {"file": ("cv.pdf", _pdf_bytes("Jean"), "application/pdf")}
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    # The blank entry is dropped, not propagated as an empty tag.
    assert body["skills"] == ["Python", "FastAPI", "PostgreSQL"]
    assert body["suggested_contract_type"] == "CDD"


def test_import_cv_drops_invalid_contract_type_suggestion(admin_client, fake_ai_client):
    fake_ai_client.response_text = json.dumps(
        {"first_name": "Jean", "suggested_contract_type": "FREELANCE"}
    )
    _enable_ai(admin_client)

    files = {"file": ("cv.pdf", _pdf_bytes("Jean"), "application/pdf")}
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["suggested_contract_type"] is None


def test_import_cv_drops_suggestion_for_unknown_department(admin_client, fake_ai_client):
    fake_ai_client.response_text = json.dumps(
        {
            "first_name": "Jean",
            "suggested_department_id": "does-not-exist",
            "suggested_position_id": "also-fake",
        }
    )
    _enable_ai(admin_client)

    files = {"file": ("cv.pdf", _pdf_bytes("Jean"), "application/pdf")}
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["suggested_department_id"] is None
    assert body["suggested_position_id"] is None


def test_import_cv_drops_position_suggestion_from_wrong_department(admin_client, fake_ai_client):
    department_id = _create_department(admin_client, "AICV2", "Dept AI CV 2")
    other_department_id = _create_department(admin_client, "AICV3", "Dept AI CV 3")
    other_position_id = _create_position(admin_client, other_department_id, "Poste ailleurs")
    fake_ai_client.response_text = json.dumps(
        {
            "first_name": "Jean",
            "suggested_department_id": department_id,
            "suggested_position_id": other_position_id,
        }
    )
    _enable_ai(admin_client)

    files = {"file": ("cv.pdf", _pdf_bytes("Jean"), "application/pdf")}
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["suggested_department_id"] == department_id
    assert body["suggested_position_id"] is None


def test_import_cv_rejects_unsupported_type_before_calling_ai(admin_client, fake_ai_client):
    _enable_ai(admin_client)
    files = {"file": ("cv.jpg", b"not-a-real-image", "image/jpeg")}
    response = admin_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 400
    assert fake_ai_client.calls == []


def test_import_cv_requires_admin(employee_client, admin_client, fake_ai_client):
    _enable_ai(admin_client)
    files = {"file": ("cv.pdf", _pdf_bytes("Test"), "application/pdf")}
    response = employee_client.post("/ai/import-cv", files=files, headers=JSON_HEADERS)
    assert response.status_code == 403


# -- Dashboard summary ---------------------------------------------------------


def test_summary_payload_contains_no_employee_names_or_ids(admin_client, fake_ai_client):
    fake_ai_client.response_text = "Synthèse : tout va bien."
    _enable_ai(admin_client)
    department_id = _create_department(admin_client, "AISUM", "Dept AI Summary")
    position_id = _create_position(admin_client, department_id, "Poste")
    employee = _create_employee(admin_client, department_id, position_id)

    response = admin_client.get("/ai/summary", headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["text"] == "Synthèse : tout va bien."

    sent_payload = fake_ai_client.calls[-1]["user"]
    assert employee["id"] not in sent_payload
    assert "Karim" not in sent_payload
    assert "Secretissimo" not in sent_payload
    assert "employee_id" not in sent_payload


def test_summary_requires_admin(make_manager_client, admin_client, fake_ai_client):
    _enable_ai(admin_client)
    department_id = _create_department(admin_client, "AISUM2", "Dept AI Summary 2")
    manager = make_manager_client(department_id, email="ai-summary-mgr@hr-management-test.dev")
    response = manager.get("/ai/summary", headers=JSON_HEADERS)
    assert response.status_code == 403


# -- Settings role gate ---------------------------------------------------------


def test_ai_settings_requires_admin(employee_client):
    response = employee_client.get("/settings/ai", headers=JSON_HEADERS)
    assert response.status_code == 403
