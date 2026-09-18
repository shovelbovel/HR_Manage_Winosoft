import pytest

from app.repositories.leave_types_repository import LeaveTypesRepository
from scripts.seed import _seed_holidays, _seed_leave_types

JSON_HEADERS = {"accept": "application/json"}

_UNIQUE_COUNTER = {"value": 0}


@pytest.fixture
def seeded_reference_data(db):
    _seed_leave_types(db)
    _seed_holidays(db)


def _leave_type_id(db, code: str) -> str:
    for leave_type in LeaveTypesRepository(db).list():
        if leave_type.code == code:
            return leave_type.id
    raise AssertionError(f"seeded leave type {code!r} not found")


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
        "cin": f"AB{100000 + n}",
        "birth_date": "1990-05-15",
        "professional_email": f"leaves-employee{n}@hr-management-test.dev",
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
    """Creates a department/position/employee and returns (employee dict,
    a TestClient logged in as that employee)."""
    department_id = _create_department(admin_client, dept_prefix[:10].upper(), f"{dept_prefix} Dept")
    position_id = _create_position(admin_client, department_id, f"{dept_prefix} Position")
    employee = _create_employee(admin_client, department_id, position_id)
    _UNIQUE_COUNTER["value"] += 1
    employee_client = make_employee_linked_client(
        employee["id"], email=f"linked{_UNIQUE_COUNTER['value']}@hr-management-test.dev"
    )
    return employee, employee_client


def test_submit_computes_working_days_excluding_weekends_and_holidays(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "wd1")
    leave_type_id = _leave_type_id(db, "ANNUAL")

    # 2026-08-14 (Fri) .. 2026-08-24 (Mon): excludes two weekends (4 days)
    # and two seeded holidays (Aug 20, Aug 21) = 5 working days out of 11.
    response = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-08-14", "end_date": "2026-08-24"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["working_days"] == 5
    assert body["status"] == "pending"
    assert body["employee_id"] == employee["id"]
    assert body["department_id"] == employee["department_id"]


def test_submit_rejected_when_balance_insufficient(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    _employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "bal1")
    leave_type_id = _leave_type_id(db, "ANNUAL")  # 18 days/year default

    response = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-01-01", "end_date": "2026-03-15"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 409


def test_submit_allowed_without_balance_for_unpaid_type(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    _employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "unpaid1")
    leave_type_id = _leave_type_id(db, "UNPAID")

    response = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-01-01", "end_date": "2026-03-15"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200, response.text


def test_submit_rejected_on_overlap_with_approved_leave(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    _employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "overlap1")
    leave_type_id = _leave_type_id(db, "ANNUAL")

    first = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-02-02", "end_date": "2026-02-04"},
        headers=JSON_HEADERS,
    ).json()
    approve_response = admin_client.post(f"/leaves/{first['id']}/approve", headers=JSON_HEADERS)
    assert approve_response.status_code == 200, approve_response.text

    second = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-02-03", "end_date": "2026-02-05"},
        headers=JSON_HEADERS,
    )
    assert second.status_code == 409


def test_approve_increments_balance_used(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "approve1")
    leave_type_id = _leave_type_id(db, "ANNUAL")

    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-03-02", "end_date": "2026-03-04"},
        headers=JSON_HEADERS,
    ).json()
    assert leave["working_days"] == 3

    admin_client.post(f"/leaves/{leave['id']}/approve", headers=JSON_HEADERS)

    balances = admin_client.get("/leaves/balances", headers=JSON_HEADERS).json()
    balance = next(b for b in balances if b["employee_id"] == employee["id"])
    assert balance["used"] == 3
    assert balance["remaining"] == 18 - 3


def test_reject_requires_reason_and_makes_no_balance_change(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "reject1")
    leave_type_id = _leave_type_id(db, "ANNUAL")

    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-04-06", "end_date": "2026-04-08"},
        headers=JSON_HEADERS,
    ).json()

    missing_reason = admin_client.post(f"/leaves/{leave['id']}/reject", json={}, headers=JSON_HEADERS)
    assert missing_reason.status_code == 400

    rejected = admin_client.post(
        f"/leaves/{leave['id']}/reject", json={"reason": "Pas assez de personnel"}, headers=JSON_HEADERS
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["rejection_reason"] == "Pas assez de personnel"

    balances = admin_client.get("/leaves/balances", headers=JSON_HEADERS).json()
    matching = [b for b in balances if b["employee_id"] == employee["id"]]
    assert not matching or matching[0]["used"] == 0


def test_approve_twice_returns_conflict(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    _employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "twice1")
    leave_type_id = _leave_type_id(db, "ANNUAL")

    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-05-04", "end_date": "2026-05-05"},
        headers=JSON_HEADERS,
    ).json()

    admin_client.post(f"/leaves/{leave['id']}/approve", headers=JSON_HEADERS)
    second_approve = admin_client.post(f"/leaves/{leave['id']}/approve", headers=JSON_HEADERS)
    assert second_approve.status_code == 409


def test_manager_outside_department_gets_404_not_403(
    admin_client, make_employee_linked_client, make_manager_client, seeded_reference_data, db
):
    employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "scope1")
    other_department_id = _create_department(admin_client, "OTHERDPT", "Autre département")
    manager_client = make_manager_client(other_department_id)

    leave_type_id = _leave_type_id(db, "ANNUAL")
    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-06-01", "end_date": "2026-06-02"},
        headers=JSON_HEADERS,
    ).json()

    view_response = manager_client.get(f"/leaves/{leave['id']}", headers=JSON_HEADERS)
    assert view_response.status_code == 404

    approve_response = manager_client.post(f"/leaves/{leave['id']}/approve", headers=JSON_HEADERS)
    assert approve_response.status_code == 404

    assert employee["department_id"] != other_department_id


def test_manager_inside_department_can_approve(
    admin_client, make_employee_linked_client, make_manager_client, seeded_reference_data, db
):
    employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "scope2")
    manager_client = make_manager_client(employee["department_id"])
    leave_type_id = _leave_type_id(db, "ANNUAL")

    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-06-08", "end_date": "2026-06-09"},
        headers=JSON_HEADERS,
    ).json()

    approve_response = manager_client.post(f"/leaves/{leave['id']}/approve", headers=JSON_HEADERS)
    assert approve_response.status_code == 200


def test_employee_viewing_another_employees_leave_gets_404(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    employee_a, client_a = _setup_employee(admin_client, make_employee_linked_client, "empscopea")
    _employee_b, client_b = _setup_employee(admin_client, make_employee_linked_client, "empscopeb")
    leave_type_id = _leave_type_id(db, "ANNUAL")

    leave = client_a.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-07-06", "end_date": "2026-07-07"},
        headers=JSON_HEADERS,
    ).json()

    response = client_b.get(f"/leaves/{leave['id']}", headers=JSON_HEADERS)
    assert response.status_code == 404
    assert employee_a["id"] != _employee_b["id"]


def test_admin_has_no_scope_restriction(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    _employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "adminscope")
    leave_type_id = _leave_type_id(db, "ANNUAL")

    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-07-13", "end_date": "2026-07-14"},
        headers=JSON_HEADERS,
    ).json()

    response = admin_client.get(f"/leaves/{leave['id']}", headers=JSON_HEADERS)
    assert response.status_code == 200


def test_manager_listing_scoped_to_own_department(
    admin_client, make_employee_linked_client, make_manager_client, seeded_reference_data, db
):
    employee_a, client_a = _setup_employee(admin_client, make_employee_linked_client, "listscopea")
    employee_b, client_b = _setup_employee(admin_client, make_employee_linked_client, "listscopeb")
    manager_client = make_manager_client(employee_a["department_id"])
    leave_type_id = _leave_type_id(db, "ANNUAL")

    client_a.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-09-07", "end_date": "2026-09-08"},
        headers=JSON_HEADERS,
    )
    client_b.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-09-07", "end_date": "2026-09-08"},
        headers=JSON_HEADERS,
    )

    pending = manager_client.get("/leaves/pending", headers=JSON_HEADERS).json()
    employee_ids = {leave["employee_id"] for leave in pending}
    assert employee_ids == {employee_a["id"]}
    assert employee_b["id"] not in employee_ids


def test_list_pending_rejects_employee_role(
    admin_client, make_employee_linked_client, seeded_reference_data
):
    _employee, employee_client = _setup_employee(admin_client, make_employee_linked_client, "empreject")
    response = employee_client.get("/leaves/pending", headers=JSON_HEADERS)
    assert response.status_code == 403


def test_submit_requires_authentication(client):
    response = client.post(
        "/leaves",
        json={"leave_type_id": "whatever", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 401


def test_submit_without_linked_employee_profile_returns_400(admin_client, seeded_reference_data, db):
    leave_type_id = _leave_type_id(db, "ANNUAL")
    response = admin_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-01-01", "end_date": "2026-01-02"},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 400
