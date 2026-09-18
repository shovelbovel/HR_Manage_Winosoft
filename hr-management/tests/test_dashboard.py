from datetime import date, timedelta

from app.repositories.leave_types_repository import LeaveTypesRepository
from scripts.seed import _seed_holidays, _seed_leave_types
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

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


def _dept_and_position(client, prefix: str):
    _UNIQUE_COUNTER["value"] += 1
    code = f"D{_UNIQUE_COUNTER['value']}"
    department_id = _create_department(client, code, f"{prefix} Department")
    position_id = _create_position(client, department_id, f"{prefix} Position")
    return department_id, position_id


def _create_employee(client, department_id: str, position_id: str, **overrides) -> dict:
    _UNIQUE_COUNTER["value"] += 1
    n = _UNIQUE_COUNTER["value"]
    payload = {
        "first_name": "Jean",
        "last_name": "Dupont",
        "cin": f"AB{100000 + n}",
        "birth_date": "1990-05-15",
        "professional_email": f"dash-employee{n}@hr-management-test.dev",
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


def _dashboard(client) -> dict:
    response = client.get("/dashboard", headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def test_employees_active_and_interns_counters_track_lifecycle(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "counters")
    before = _dashboard(admin_client)

    employee = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="STAGE",
        trial_end_date_override="2024-06-01",
    )
    after_create = _dashboard(admin_client)
    assert after_create["employees_active"] == before["employees_active"] + 1
    assert after_create["interns"] == before["interns"] + 1

    admin_client.post(f"/employees/{employee['id']}/deactivate", headers=JSON_HEADERS)
    after_deactivate = _dashboard(admin_client)
    assert after_deactivate["employees_active"] == before["employees_active"]
    assert after_deactivate["interns"] == before["interns"]

    admin_client.post(f"/employees/{employee['id']}/activate", headers=JSON_HEADERS)
    after_activate = _dashboard(admin_client)
    assert after_activate["employees_active"] == before["employees_active"] + 1
    assert after_activate["interns"] == before["interns"] + 1


def test_leaves_pending_counter_tracks_submit_approve_reject(
    admin_client, make_employee_linked_client, db
):
    _seed_leave_types(db)
    _seed_holidays(db)
    department_id, position_id = _dept_and_position(admin_client, "leavescounter")
    employee = _create_employee(admin_client, department_id, position_id)
    employee_client = make_employee_linked_client(
        employee["id"], email="dashleave1@hr-management-test.dev"
    )
    leave_type_id = next(
        lt.id for lt in LeaveTypesRepository(db).list() if lt.code == "ANNUAL"
    )

    before = _dashboard(admin_client)
    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-01-05", "end_date": "2026-01-06"},
        headers=JSON_HEADERS,
    ).json()
    after_submit = _dashboard(admin_client)
    assert after_submit["leaves_pending"] == before["leaves_pending"] + 1

    admin_client.post(f"/leaves/{leave['id']}/approve", headers=JSON_HEADERS)
    after_approve = _dashboard(admin_client)
    assert after_approve["leaves_pending"] == before["leaves_pending"]

    leave2 = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-02-02", "end_date": "2026-02-03"},
        headers=JSON_HEADERS,
    ).json()
    after_second_submit = _dashboard(admin_client)
    assert after_second_submit["leaves_pending"] == before["leaves_pending"] + 1

    admin_client.post(
        f"/leaves/{leave2['id']}/reject", json={"reason": "Non"}, headers=JSON_HEADERS
    )
    after_reject = _dashboard(admin_client)
    assert after_reject["leaves_pending"] == before["leaves_pending"]


def test_contracts_expiring_window_excludes_out_of_range(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "expiring")
    today = date.today()
    inside = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="CDD",
        contract_end_date=(today + timedelta(days=10)).isoformat(),
    )
    outside = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="CDD",
        contract_end_date=(today + timedelta(days=45)).isoformat(),
    )

    snapshot = _dashboard(admin_client)
    ids = {employee["id"] for employee in snapshot["contracts_expiring"]}
    assert inside["id"] in ids
    assert outside["id"] not in ids


def test_interns_ending_soon_excludes_out_of_range_and_non_interns(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "internsending")
    today = date.today()
    ending_soon_intern = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="STAGE",
        trial_end_date_override=(today + timedelta(days=5)).isoformat(),
        contract_end_date=(today + timedelta(days=5)).isoformat(),
    )
    ending_later_intern = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="STAGE",
        trial_end_date_override=(today + timedelta(days=25)).isoformat(),
        contract_end_date=(today + timedelta(days=25)).isoformat(),
    )
    ending_soon_non_intern = _create_employee(
        admin_client,
        department_id,
        position_id,
        contract_type="CDD",
        contract_end_date=(today + timedelta(days=5)).isoformat(),
    )

    snapshot = _dashboard(admin_client)
    ids = {employee["id"] for employee in snapshot["interns_ending_soon"]}
    assert ending_soon_intern["id"] in ids
    assert ending_later_intern["id"] not in ids
    assert ending_soon_non_intern["id"] not in ids


def test_birthdays_this_month_filtering(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "birthdays")
    today = date.today()
    this_month_birth = date(1990, today.month, min(today.day, 28)).isoformat()
    other_month = (today.month % 12) + 1
    other_month_birth = date(1990, other_month, 15).isoformat()

    this_month_employee = _create_employee(
        admin_client, department_id, position_id, birth_date=this_month_birth
    )
    other_month_employee = _create_employee(
        admin_client, department_id, position_id, birth_date=other_month_birth
    )

    snapshot = _dashboard(admin_client)
    ids = {employee["id"] for employee in snapshot["birthdays_this_month"]}
    assert this_month_employee["id"] in ids
    assert other_month_employee["id"] not in ids


def test_new_hires_this_month_includes_recently_created_employee(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "newhires")
    employee = _create_employee(admin_client, department_id, position_id)

    snapshot = _dashboard(admin_client)
    ids = {e["id"] for e in snapshot["new_hires_this_month"]}
    assert employee["id"] in ids


def test_manager_dashboard_scoped_to_own_department(admin_client, make_manager_client):
    dept_a, pos_a = _dept_and_position(admin_client, "scopea")
    dept_b, pos_b = _dept_and_position(admin_client, "scopeb")
    _employee_a = _create_employee(admin_client, dept_a, pos_a)
    employee_b = _create_employee(admin_client, dept_b, pos_b)

    manager_client = make_manager_client(dept_a)
    snapshot = _dashboard(manager_client)

    assert snapshot["departments_active"] is None
    assert snapshot["employees_active"] == 1
    dept_names = {name for name, _count in snapshot["department_distribution"]}
    assert employee_b["department_name"] not in dept_names


def test_dashboard_requires_authentication(client):
    response = client.get("/dashboard", headers=JSON_HEADERS)
    assert response.status_code == 401


def test_dashboard_rejects_employee_role(employee_client):
    response = employee_client.get("/dashboard", headers=JSON_HEADERS)
    assert response.status_code == 403


def test_login_redirects_admin_to_dashboard(seeded_admin, client):
    response = client.post(
        "/login",
        data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_login_redirects_manager_to_dashboard(admin_client, make_manager_client, client):
    department_id, _position_id = _dept_and_position(admin_client, "loginmanager")
    make_manager_client(department_id, email="loginmanager1@hr-management-test.dev")

    response = client.post(
        "/login",
        data={"email": "loginmanager1@hr-management-test.dev", "password": "CorrectHorse123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_login_redirects_employee_to_home(
    admin_client, make_employee_linked_client, client
):
    department_id, position_id = _dept_and_position(admin_client, "loginemployee")
    employee = _create_employee(admin_client, department_id, position_id)
    make_employee_linked_client(
        employee["id"], email="loginemployee1@hr-management-test.dev"
    )

    response = client.post(
        "/login",
        data={"email": "loginemployee1@hr-management-test.dev", "password": "CorrectHorse123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/home"
