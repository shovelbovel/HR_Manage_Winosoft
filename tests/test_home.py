from app.repositories.leave_types_repository import LeaveTypesRepository
from scripts.seed import _seed_holidays, _seed_leave_types

JSON_HEADERS = {"accept": "application/json"}

_UNIQUE_COUNTER = {"value": 0}


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
        "first_name": "Jean",
        "last_name": "Dupont",
        "cin": f"AB{200000 + n}",
        "birth_date": "1990-05-15",
        "professional_email": f"home-employee{n}@hr-management-test.dev",
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


def _setup_employee(admin_client, make_employee_linked_client, dept_prefix: str):
    department_id = _create_department(admin_client, dept_prefix[:10].upper(), f"{dept_prefix} Dept")
    position_id = _create_position(admin_client, department_id, f"{dept_prefix} Position")
    employee = _create_employee(admin_client, department_id, position_id)
    _UNIQUE_COUNTER["value"] += 1
    employee_client = make_employee_linked_client(
        employee["id"], email=f"home-linked{_UNIQUE_COUNTER['value']}@hr-management-test.dev"
    )
    return employee, employee_client


def test_home_returns_balances_and_recent_leaves_for_linked_employee(
    admin_client, make_employee_linked_client, db
):
    _seed_leave_types(db)
    _seed_holidays(db)
    _employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "homebal")
    leave_type_id = next(
        lt.id for lt in LeaveTypesRepository(db).list() if lt.code == "ANNUAL"
    )

    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-01-05", "end_date": "2026-01-06"},
        headers=JSON_HEADERS,
    ).json()

    response = employee_client.get("/home", headers=JSON_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["has_employee_profile"] is True
    assert any(balance["leave_type_name"] for balance in body["balances"])
    assert leave["id"] in {entry["id"] for entry in body["recent_leaves"]}


def test_home_returns_empty_snapshot_for_admin_without_employee_profile(admin_client):
    response = admin_client.get("/home", headers=JSON_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["has_employee_profile"] is False
    assert body["balances"] == []
    assert body["recent_leaves"] == []


def test_home_requires_authentication(client):
    response = client.get("/home", headers=JSON_HEADERS)
    assert response.status_code == 401
