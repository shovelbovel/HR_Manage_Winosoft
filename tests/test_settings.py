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


def _create_employee(client, department_id: str, position_id: str) -> dict:
    _UNIQUE_COUNTER["value"] += 1
    n = _UNIQUE_COUNTER["value"]
    payload = {
        "first_name": "Jean",
        "last_name": "Dupont",
        "cin": f"AB{500000 + n}",
        "birth_date": "1990-05-15",
        "professional_email": f"settings-employee{n}@hr-management-test.dev",
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
    response = client.post("/employees", json=payload, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def test_get_company_settings_returns_none_when_unset(admin_client):
    response = admin_client.get("/settings/company", headers=JSON_HEADERS)
    assert response.status_code == 200
    assert response.json() is None


def test_admin_can_set_and_read_company_settings(admin_client):
    payload = {
        "name": "WinoSoft SARLAU",
        "address": "26, Av Mers Sultan, Casablanca",
        "ice": "003504275000024",
        "rc": "632091",
        "if_number": "65974019",
    }
    response = admin_client.post("/settings/company", json=payload, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "WinoSoft SARLAU"

    read_back = admin_client.get("/settings/company", headers=JSON_HEADERS).json()
    assert read_back["ice"] == "003504275000024"


def test_settings_requires_authentication(client):
    response = client.get("/settings/company", headers=JSON_HEADERS)
    assert response.status_code == 401


def test_settings_rejects_non_admin(employee_client):
    response = employee_client.get("/settings/company", headers=JSON_HEADERS)
    assert response.status_code == 403


# -- Congés -----------------------------------------------------------------


def test_create_and_update_leave_type(admin_client):
    payload = {
        "code": "SABBATICAL",
        "name": "Congé sabbatique",
        "default_days_per_year": 0,
        "is_deductible": False,
        "requires_justification": True,
    }
    created = admin_client.post("/settings/leaves/leave-types", json=payload, headers=JSON_HEADERS)
    assert created.status_code == 200, created.text
    leave_type_id = created.json()["id"]

    duplicate = admin_client.post("/settings/leaves/leave-types", json=payload, headers=JSON_HEADERS)
    assert duplicate.status_code == 409

    update_payload = {
        "name": "Congé sabbatique renommé",
        "default_days_per_year": 5,
        "is_deductible": True,
        "requires_justification": False,
    }
    updated = admin_client.post(
        f"/settings/leaves/leave-types/{leave_type_id}", json=update_payload, headers=JSON_HEADERS
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["name"] == "Congé sabbatique renommé"
    assert body["code"] == "SABBATICAL"  # immutable


def test_create_leave_type_rejects_non_admin(make_manager_client):
    manager = make_manager_client("some-department", email="settings-mgr1@hr-management-test.dev")
    response = manager.post(
        "/settings/leaves/leave-types",
        json={
            "code": "X",
            "name": "X",
            "is_deductible": False,
            "requires_justification": False,
        },
        headers=JSON_HEADERS,
    )
    assert response.status_code == 403


def test_create_recurring_holiday(admin_client):
    response = admin_client.post(
        "/settings/leaves/holidays",
        json={"name": "Fête de l'Indépendance", "is_recurring": True, "month": 11, "day": 18},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_recurring"] is True
    assert body["year"] is None


def test_non_recurring_holiday_requires_year(admin_client):
    response = admin_client.post(
        "/settings/leaves/holidays",
        json={"name": "Aïd al-Fitr", "is_recurring": False, "month": 4, "day": 20},
        headers=JSON_HEADERS,
    )
    assert response.status_code == 400

    with_year = admin_client.post(
        "/settings/leaves/holidays",
        json={
            "name": "Aïd al-Fitr",
            "is_recurring": False,
            "month": 4,
            "day": 20,
            "year": 2026,
        },
        headers=JSON_HEADERS,
    )
    assert with_year.status_code == 200, with_year.text
    assert with_year.json()["year"] == 2026


def test_delete_holiday(admin_client):
    created = admin_client.post(
        "/settings/leaves/holidays",
        json={"name": "Temporaire", "is_recurring": True, "month": 6, "day": 6},
        headers=JSON_HEADERS,
    ).json()

    delete_response = admin_client.post(
        f"/settings/leaves/holidays/{created['id']}/delete", headers=JSON_HEADERS
    )
    assert delete_response.status_code == 200

    holidays = admin_client.get("/settings/leaves", headers=JSON_HEADERS).json()["holidays"]
    assert created["id"] not in {h["id"] for h in holidays}


# -- Utilisateurs -------------------------------------------------------------


def test_create_manager_requires_department_id(admin_client):
    missing_department = admin_client.post(
        "/settings/users",
        json={
            "email": "settings-mgr2@hr-management-test.dev",
            "password": "GoodPass123",
            "role": "manager",
        },
        headers=JSON_HEADERS,
    )
    assert missing_department.status_code == 400

    department_id = _create_department(admin_client, "SETTMGR", "Dept SettMgr")
    ok = admin_client.post(
        "/settings/users",
        json={
            "email": "settings-mgr3@hr-management-test.dev",
            "password": "GoodPass123",
            "role": "manager",
            "department_id": department_id,
        },
        headers=JSON_HEADERS,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["department_id"] == department_id


def test_create_employee_user_validates_employee_id(admin_client):
    department_id = _create_department(admin_client, "SETTEMP", "Dept SettEmp")
    position_id = _create_position(admin_client, department_id, "Poste")
    employee = _create_employee(admin_client, department_id, position_id)

    bogus = admin_client.post(
        "/settings/users",
        json={
            "email": "settings-emp-bogus@hr-management-test.dev",
            "password": "GoodPass123",
            "role": "employee",
            "employee_id": "does-not-exist",
        },
        headers=JSON_HEADERS,
    )
    assert bogus.status_code == 404

    linked = admin_client.post(
        "/settings/users",
        json={
            "email": "settings-emp-linked@hr-management-test.dev",
            "password": "GoodPass123",
            "role": "employee",
            "employee_id": employee["id"],
        },
        headers=JSON_HEADERS,
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["employee_id"] == employee["id"]


def test_weak_password_rejected(admin_client):
    response = admin_client.post(
        "/settings/users",
        json={
            "email": "settings-weak@hr-management-test.dev",
            "password": "alllowercase1",  # no uppercase
            "role": "admin",
        },
        headers=JSON_HEADERS,
    )
    assert response.status_code == 400


def test_reset_password_then_login_flow(admin_client, client):
    created = admin_client.post(
        "/settings/users",
        json={
            "email": "settings-resetflow@hr-management-test.dev",
            "password": "OldPass123",
            "role": "admin",
        },
        headers=JSON_HEADERS,
    ).json()

    old_login = client.post(
        "/login",
        data={"email": "settings-resetflow@hr-management-test.dev", "password": "OldPass123"},
    )
    assert old_login.status_code == 200

    reset = admin_client.post(
        f"/settings/users/{created['id']}/reset-password",
        json={"password": "NewPass456"},
        headers=JSON_HEADERS,
    )
    assert reset.status_code == 200, reset.text

    old_login_after_reset = client.post(
        "/login",
        data={"email": "settings-resetflow@hr-management-test.dev", "password": "OldPass123"},
    )
    assert old_login_after_reset.status_code == 401

    new_login = client.post(
        "/login",
        data={"email": "settings-resetflow@hr-management-test.dev", "password": "NewPass456"},
        follow_redirects=False,
    )
    assert new_login.status_code == 303


def test_deactivate_and_activate_user(admin_client, client):
    created = admin_client.post(
        "/settings/users",
        json={
            "email": "settings-toggle@hr-management-test.dev",
            "password": "GoodPass123",
            "role": "admin",
        },
        headers=JSON_HEADERS,
    ).json()

    deactivate = admin_client.post(
        f"/settings/users/{created['id']}/deactivate", headers=JSON_HEADERS
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    blocked_login = client.post(
        "/login",
        data={"email": "settings-toggle@hr-management-test.dev", "password": "GoodPass123"},
    )
    assert blocked_login.status_code == 401

    activate = admin_client.post(f"/settings/users/{created['id']}/activate", headers=JSON_HEADERS)
    assert activate.status_code == 200
    assert activate.json()["is_active"] is True

    working_login = client.post(
        "/login",
        data={"email": "settings-toggle@hr-management-test.dev", "password": "GoodPass123"},
        follow_redirects=False,
    )
    assert working_login.status_code == 303


def test_reactivating_conflicts_if_email_reused_in_the_meantime(admin_client):
    created = admin_client.post(
        "/settings/users",
        json={
            "email": "settings-reuse@hr-management-test.dev",
            "password": "GoodPass123",
            "role": "admin",
        },
        headers=JSON_HEADERS,
    ).json()
    admin_client.post(f"/settings/users/{created['id']}/deactivate", headers=JSON_HEADERS)

    # The email is now free — a brand new account can claim it.
    reused = admin_client.post(
        "/settings/users",
        json={
            "email": "settings-reuse@hr-management-test.dev",
            "password": "GoodPass123",
            "role": "admin",
        },
        headers=JSON_HEADERS,
    )
    assert reused.status_code == 200, reused.text

    conflict = admin_client.post(f"/settings/users/{created['id']}/activate", headers=JSON_HEADERS)
    assert conflict.status_code == 409


def test_users_list_and_detail_require_admin(employee_client):
    list_response = employee_client.get("/settings/users", headers=JSON_HEADERS)
    assert list_response.status_code == 403


def test_user_detail_404_for_unknown_id(admin_client):
    response = admin_client.get("/settings/users/does-not-exist", headers=JSON_HEADERS)
    assert response.status_code == 404
