import re
from datetime import date, timedelta

JSON_HEADERS = {"accept": "application/json"}

_UNIQUE_COUNTER = {"value": 0}
_HIRE_DATE = date(2026, 1, 5)


def _create_department(client, code: str, name: str) -> str:
    response = client.post("/departments", json={"code": code, "name": name}, headers=JSON_HEADERS)
    return response.json()["id"]


def _create_position(client, department_id: str, title: str) -> str:
    response = client.post(
        "/positions", json={"department_id": department_id, "title": title}, headers=JSON_HEADERS
    )
    return response.json()["id"]


def _dept_and_position(client, prefix: str):
    _UNIQUE_COUNTER["value"] += 1
    code = f"D{_UNIQUE_COUNTER['value']}"
    department_id = _create_department(client, code, f"{prefix} Department")
    position_id = _create_position(client, department_id, f"{prefix} Position")
    return department_id, position_id


def _create_employee(client, department_id: str, position_id: str, **overrides):
    _UNIQUE_COUNTER["value"] += 1
    n = _UNIQUE_COUNTER["value"]
    payload = {
        "first_name": "Jean",
        "last_name": "Dupont",
        "cin": f"AB{100000 + n}",
        "birth_date": "1990-05-15",
        "professional_email": f"trial-employee{n}@hr-management-test.dev",
        "phone": "0612345678",
        "department_id": department_id,
        "position_id": position_id,
        "hire_date": _HIRE_DATE.isoformat(),
        "contract_type": "CDI",
        "contract_category": "EMPLOYEE",
        "contract_start_date": _HIRE_DATE.isoformat(),
        "gross_salary": 8000,
        "rib": "1" * 24,
        "cnss_number": "1234567",
        "emergency_contact_name": "Marie Dupont",
        "emergency_contact_phone": "0612345679",
    }
    payload.update(overrides)
    return client.post("/employees", json=payload, headers=JSON_HEADERS)


def _get_trial(client, employee_id: str) -> dict:
    response = client.get(f"/trials/{employee_id}", headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def test_cdi_cadre_gets_90_day_trial_period(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "cadre")
    employee = _create_employee(
        admin_client, department_id, position_id, contract_category="CADRE"
    ).json()

    trial = _get_trial(admin_client, employee["id"])
    assert trial["status"] == "pending"
    expected_end = (_HIRE_DATE + timedelta(days=90)).isoformat()
    assert trial["initial_end_date"].startswith(expected_end)


def test_cdi_employee_category_gets_45_day_trial_period(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "cdiemp")
    employee = _create_employee(
        admin_client, department_id, position_id, contract_category="EMPLOYEE"
    ).json()

    trial = _get_trial(admin_client, employee["id"])
    expected_end = (_HIRE_DATE + timedelta(days=45)).isoformat()
    assert trial["initial_end_date"].startswith(expected_end)


def test_cdi_ouvrier_gets_15_day_trial_period(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "ouvrier")
    employee = _create_employee(
        admin_client, department_id, position_id, contract_category="OUVRIER"
    ).json()

    trial = _get_trial(admin_client, employee["id"])
    expected_end = (_HIRE_DATE + timedelta(days=15)).isoformat()
    assert trial["initial_end_date"].startswith(expected_end)


def test_cdd_short_contract_trial_capped_at_two_weeks(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "cddshort")
    contract_end = _HIRE_DATE + timedelta(weeks=20)  # 140 days, < 182-day threshold
    employee = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="CDD",
        contract_end_date=contract_end.isoformat(),
    ).json()

    trial = _get_trial(admin_client, employee["id"])
    expected_end = (_HIRE_DATE + timedelta(days=14)).isoformat()  # capped at 2 weeks
    assert trial["initial_end_date"].startswith(expected_end)


def test_cdd_long_contract_flat_30_day_trial(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "cddlong")
    contract_end = _HIRE_DATE + timedelta(days=200)  # >= 182-day threshold
    employee = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="CDD",
        contract_end_date=contract_end.isoformat(),
    ).json()

    trial = _get_trial(admin_client, employee["id"])
    expected_end = (_HIRE_DATE + timedelta(days=30)).isoformat()
    assert trial["initial_end_date"].startswith(expected_end)


def test_stage_without_override_rejected(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "stagenoover")
    response = _create_employee(admin_client, department_id, position_id, contract_type="STAGE")
    assert response.status_code == 400


def test_stage_with_override_uses_override_exactly(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "stageover")
    override = _HIRE_DATE + timedelta(days=60)
    employee = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="STAGE",
        trial_end_date_override=override.isoformat(),
    ).json()

    trial = _get_trial(admin_client, employee["id"])
    assert trial["initial_end_date"].startswith(override.isoformat())


def test_cdi_without_category_rejected(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "cdinoocat")
    response = _create_employee(
        admin_client, department_id, position_id, contract_category=None
    )
    assert response.status_code == 400


def test_cdd_without_end_date_rejected(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "cddnoend")
    response = _create_employee(admin_client, department_id, position_id, contract_type="CDD")
    assert response.status_code == 400


def test_validate_flips_employee_status_to_active(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "validate")
    employee = _create_employee(admin_client, department_id, position_id).json()
    assert employee["status"] == "trial"

    response = admin_client.post(
        f"/trials/{employee['id']}/validate",
        json={"reason": "Bonne intégration"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "validated"

    updated_employee = admin_client.get(f"/employees/{employee['id']}", headers=JSON_HEADERS).json()
    assert updated_employee["status"] == "active"


def test_validate_twice_returns_409(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "validatetwice")
    employee = _create_employee(admin_client, department_id, position_id).json()

    admin_client.post(
        f"/trials/{employee['id']}/validate", json={"reason": "OK"}, headers=JSON_HEADERS
    )
    second = admin_client.post(
        f"/trials/{employee['id']}/validate", json={"reason": "OK"}, headers=JSON_HEADERS
    )
    assert second.status_code == 409


def test_extend_cdi_once_then_conflict(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "extendcdi")
    employee = _create_employee(admin_client, department_id, position_id).json()

    first = admin_client.post(
        f"/trials/{employee['id']}/extend",
        json={"reason": "Besoin de plus de temps"},
        headers=JSON_HEADERS,
    )
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "extended"
    # Employé category: 45-day initial duration, doubled after one extension.
    expected_extended_end = (_HIRE_DATE + timedelta(days=90)).isoformat()
    assert body["extended_end_date"].startswith(expected_extended_end)

    second = admin_client.post(
        f"/trials/{employee['id']}/extend", json={"reason": "Encore"}, headers=JSON_HEADERS
    )
    assert second.status_code == 409


def test_extend_cdd_not_renewable(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "extendcdd")
    contract_end = _HIRE_DATE + timedelta(weeks=10)
    employee = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="CDD",
        contract_end_date=contract_end.isoformat(),
    ).json()

    response = admin_client.post(
        f"/trials/{employee['id']}/extend", json={"reason": "Essai"}, headers=JSON_HEADERS
    )
    assert response.status_code == 409


def test_refuse_requires_reason(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "refusenoreason")
    employee = _create_employee(admin_client, department_id, position_id).json()

    response = admin_client.post(
        f"/trials/{employee['id']}/refuse", json={}, headers=JSON_HEADERS
    )
    assert response.status_code == 400


def test_refuse_succeeds_and_leaves_employee_status_untouched(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "refuseok")
    employee = _create_employee(admin_client, department_id, position_id).json()

    response = admin_client.post(
        f"/trials/{employee['id']}/refuse",
        json={"reason": "Compétences insuffisantes"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "refused"

    updated_employee = admin_client.get(f"/employees/{employee['id']}", headers=JSON_HEADERS).json()
    assert updated_employee["status"] == "trial"


def test_list_current_and_history_split(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "split")
    current_employee = _create_employee(admin_client, department_id, position_id).json()
    decided_employee = _create_employee(admin_client, department_id, position_id).json()
    admin_client.post(
        f"/trials/{decided_employee['id']}/validate",
        json={"reason": "OK"},
        headers=JSON_HEADERS,
    )

    current = admin_client.get("/trials", headers=JSON_HEADERS).json()
    current_ids = {trial["id"] for trial in current}
    assert current_employee["id"] in current_ids
    assert decided_employee["id"] not in current_ids

    history = admin_client.get("/trials/history", headers=JSON_HEADERS).json()
    history_ids = {trial["id"] for trial in history}
    assert decided_employee["id"] in history_ids
    assert current_employee["id"] not in history_ids


def test_progress_bar_present_and_within_bounds(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "progress")
    employee = _create_employee(admin_client, department_id, position_id).json()

    response = admin_client.get(f"/trials/{employee['id']}")
    assert response.status_code == 200
    match = re.search(r'progress-bar[^>]*style="width:\s*(\d+)%', response.text)
    assert match is not None
    percent = int(match.group(1))
    assert 0 <= percent <= 100


def test_list_current_requires_authentication(client):
    response = client.get("/trials", headers=JSON_HEADERS)
    assert response.status_code == 401


def test_list_current_rejects_non_admin(employee_client):
    response = employee_client.get("/trials", headers=JSON_HEADERS)
    assert response.status_code == 403
