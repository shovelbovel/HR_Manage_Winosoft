"""Tests for app/services/attrition_service.py — the local (non-AI-vendor)
attrition-risk model trained by ml/train_attrition_model.py.

Unlike tests/test_ai.py, these never touch a network call — this is a
locally-loaded scikit-learn pipeline, scored in-process.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import ContractType, EmployeeDocument, EmployeeStatus
from app.services import attrition_service

JSON_HEADERS = {"accept": "application/json"}
_UNIQUE_COUNTER = {"value": 0}


def _make_employee(
    *, birth_years_ago: float, hire_years_ago: float, department_name: str = "Informatique"
) -> EmployeeDocument:
    now = datetime.now(timezone.utc)
    return EmployeeDocument(
        id="emp-1",
        matricule="EMP-2026-0001",
        first_name="Jean",
        last_name="Dupont",
        cin="AB123456",
        birth_date=now - timedelta(days=birth_years_ago * 365.25),
        birth_month=(now - timedelta(days=birth_years_ago * 365.25)).month,
        professional_email="jean.dupont@example.com",
        phone="0612345678",
        department_id="dept-1",
        department_name=department_name,
        position_id="pos-1",
        position_title="Développeur Backend",
        hire_date=now - timedelta(days=hire_years_ago * 365.25),
        contract_type=ContractType.CDI,
        contract_start_date=now - timedelta(days=hire_years_ago * 365.25),
        status=EmployeeStatus.ACTIVE,
        gross_salary_encrypted="unused-in-this-test",
        rib_encrypted="unused-in-this-test",
        cnss_number="1234567",
        emergency_contact_name="Marie Dupont",
        emergency_contact_phone="0612345679",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def _reset_cache():
    # Each test starts from a clean slate regardless of load order/outcome
    # of a previous test in this module.
    attrition_service.reset_model_cache()
    yield
    attrition_service.reset_model_cache()


def test_score_employee_returns_valid_probability_when_model_present():
    employee = _make_employee(birth_years_ago=35, hire_years_ago=3)
    result = attrition_service.score_employee(employee, gross_salary=9000)

    if not result.available:
        pytest.skip("ml/artifacts/attrition_model.joblib not trained in this environment")

    assert 0.0 <= result.probability <= 1.0
    assert result.label in {"Faible", "Modéré", "Élevé"}
    assert result.total_features > 0
    assert 0 <= result.defaulted_count <= result.total_features
    # Age, tenure and salary are always suppliable from an Employee record,
    # so at least that many real (non-defaulted) inputs should be used.
    assert len(result.used_features) >= 3


def test_score_employee_gracefully_degrades_when_model_missing(monkeypatch):
    monkeypatch.setattr(attrition_service, "_MODEL_PATH", attrition_service._MODEL_PATH.parent / "does-not-exist.joblib")
    employee = _make_employee(birth_years_ago=30, hire_years_ago=1)

    result = attrition_service.score_employee(employee, gross_salary=6000)

    assert result.available is False
    assert result.probability is None
    assert result.label is None


def test_score_employee_handles_unmapped_department_without_crashing():
    # "Finance" and "Commercial" have no entry in the app→dataset department
    # mapping — must fall through to the encoder's handle_unknown="ignore"
    # rather than raising.
    employee = _make_employee(birth_years_ago=28, hire_years_ago=2, department_name="Finance")
    result = attrition_service.score_employee(employee, gross_salary=7000)

    if not result.available:
        pytest.skip("ml/artifacts/attrition_model.joblib not trained in this environment")
    assert 0.0 <= result.probability <= 1.0


# -- Integration: the risk card actually renders on the employee page ---------


def _create_department(client, code: str, name: str) -> str:
    response = client.post("/departments", json={"code": code, "name": name}, headers=JSON_HEADERS)
    return response.json()["id"]


def _create_position(client, department_id: str, title: str) -> str:
    response = client.post(
        "/positions", json={"department_id": department_id, "title": title}, headers=JSON_HEADERS
    )
    return response.json()["id"]


def test_employee_detail_page_renders_risk_card(admin_client):
    _UNIQUE_COUNTER["value"] += 1
    n = _UNIQUE_COUNTER["value"]
    department_id = _create_department(admin_client, f"ATR{n}", "Dept Attrition")
    position_id = _create_position(admin_client, department_id, "Poste Attrition")
    payload = {
        "first_name": "Karim",
        "last_name": "Bennis",
        "cin": f"AB{900000 + n}",
        "birth_date": "1988-03-12",
        "professional_email": f"attrition-test{n}@hr-management-test.dev",
        "phone": "0612345678",
        "department_id": department_id,
        "position_id": position_id,
        "hire_date": "2023-01-01",
        "contract_type": "CDI",
        "contract_category": "EMPLOYEE",
        "contract_start_date": "2023-01-01",
        "gross_salary": 9500,
        "rib": "1" * 24,
        "cnss_number": "1234567",
        "emergency_contact_name": "Sara Bennis",
        "emergency_contact_phone": "0612345679",
    }
    created = admin_client.post("/employees", json=payload, headers=JSON_HEADERS)
    assert created.status_code == 200, created.text
    employee_id = created.json()["id"]

    response = admin_client.get(f"/employees/{employee_id}")
    assert response.status_code == 200
    # Either the risk card or the explicit "unavailable" fallback must be
    # present — the page must never silently omit both or crash.
    assert ("Risque de départ" in response.text) or ("indisponible" in response.text)
