from datetime import date

JSON_HEADERS = {"accept": "application/json"}

_UNIQUE_COUNTER = {"value": 0}


def _create_department(client, code: str, name: str) -> str:
    response = client.post(
        "/departments", json={"code": code, "name": name}, headers=JSON_HEADERS
    )
    return response.json()["id"]


def _create_position(client, department_id: str, title: str, max_occupants=None):
    payload = {"department_id": department_id, "title": title}
    if max_occupants is not None:
        payload["max_occupants"] = max_occupants
    return client.post("/positions", json=payload, headers=JSON_HEADERS)


def _dept_and_position(client, prefix: str, max_occupants=None):
    _UNIQUE_COUNTER["value"] += 1
    code = f"D{_UNIQUE_COUNTER['value']}"
    department_id = _create_department(client, code, f"{prefix} Department")
    position_id = _create_position(client, department_id, f"{prefix} Position", max_occupants).json()[
        "id"
    ]
    return department_id, position_id


def _valid_employee_payload(department_id: str, position_id: str, **overrides) -> dict:
    # Unique per call so CIN/email don't collide across tests that don't
    # care about uniqueness themselves.
    _UNIQUE_COUNTER["value"] += 1
    n = _UNIQUE_COUNTER["value"]
    payload = {
        "first_name": "Jean",
        "last_name": "Dupont",
        "cin": f"AB{100000 + n}",
        "birth_date": "1990-05-15",
        "professional_email": f"employee{n}@hr-management-test.dev",
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
    return payload


def _create_employee(client, department_id: str, position_id: str, **overrides):
    payload = _valid_employee_payload(department_id, position_id, **overrides)
    return client.post("/employees", json=payload, headers=JSON_HEADERS)


def test_create_employee_success_matricule_format_and_increment(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "matricule")

    first = _create_employee(admin_client, department_id, position_id)
    assert first.status_code == 200
    year = date.today().year
    assert first.json()["matricule"] == f"EMP-{year}-0001"
    assert first.json()["status"] == "trial"

    second = _create_employee(admin_client, department_id, position_id)
    assert second.status_code == 200
    assert second.json()["matricule"] == f"EMP-{year}-0002"


def test_create_employee_invalid_cin_rejected(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "badcin")
    response = _create_employee(admin_client, department_id, position_id, cin="not-a-cin")
    assert response.status_code == 400


def test_create_employee_invalid_phone_rejected(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "badphone")
    response = _create_employee(admin_client, department_id, position_id, phone="123")
    assert response.status_code == 400


def test_create_employee_invalid_rib_rejected(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "badrib")
    response = _create_employee(admin_client, department_id, position_id, rib="123")
    assert response.status_code == 400


def test_create_employee_under_minimum_age_rejected(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "minor")
    too_young_birth_date = f"{date.today().year - 5}-01-01"
    response = _create_employee(
        admin_client, department_id, position_id, birth_date=too_young_birth_date
    )
    assert response.status_code == 400


def test_create_employee_duplicate_cin_conflict(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "dupcin")
    shared_cin = "CD999999"
    first = _create_employee(admin_client, department_id, position_id, cin=shared_cin)
    assert first.status_code == 200

    second = _create_employee(admin_client, department_id, position_id, cin=shared_cin)
    assert second.status_code == 409


def test_create_employee_duplicate_email_conflict(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "dupemail")
    shared_email = "duplicate@hr-management-test.dev"
    first = _create_employee(
        admin_client, department_id, position_id, professional_email=shared_email
    )
    assert first.status_code == 200

    second = _create_employee(
        admin_client, department_id, position_id, professional_email=shared_email
    )
    assert second.status_code == 409


def test_department_and_position_counters_increment_on_create(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "counters")
    _create_employee(admin_client, department_id, position_id)

    department = admin_client.get(f"/departments/{department_id}", headers=JSON_HEADERS).json()
    position = admin_client.get(f"/positions/{position_id}", headers=JSON_HEADERS).json()
    assert department["employee_count"] == 1
    assert position["occupant_count"] == 1


def test_counters_decrement_on_deactivate_and_reincrement_on_activate(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "toggle")
    employee = _create_employee(admin_client, department_id, position_id).json()

    admin_client.post(f"/employees/{employee['id']}/deactivate", headers=JSON_HEADERS)
    department = admin_client.get(f"/departments/{department_id}", headers=JSON_HEADERS).json()
    position = admin_client.get(f"/positions/{position_id}", headers=JSON_HEADERS).json()
    assert department["employee_count"] == 0
    assert position["occupant_count"] == 0

    status_response = admin_client.get(f"/employees/{employee['id']}", headers=JSON_HEADERS)
    assert status_response.json()["status"] == "inactive"

    admin_client.post(f"/employees/{employee['id']}/activate", headers=JSON_HEADERS)
    department = admin_client.get(f"/departments/{department_id}", headers=JSON_HEADERS).json()
    position = admin_client.get(f"/positions/{position_id}", headers=JSON_HEADERS).json()
    assert department["employee_count"] == 1
    assert position["occupant_count"] == 1


def test_deactivate_is_idempotent_no_double_decrement(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "idempotent")
    employee = _create_employee(admin_client, department_id, position_id).json()

    admin_client.post(f"/employees/{employee['id']}/deactivate", headers=JSON_HEADERS)
    admin_client.post(f"/employees/{employee['id']}/deactivate", headers=JSON_HEADERS)

    department = admin_client.get(f"/departments/{department_id}", headers=JSON_HEADERS).json()
    assert department["employee_count"] == 0


def test_position_capacity_exceeded(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "capacity", max_occupants=1)

    first = _create_employee(admin_client, department_id, position_id)
    assert first.status_code == 200

    second = _create_employee(admin_client, department_id, position_id)
    assert second.status_code == 409


def test_position_department_mismatch_rejected(admin_client):
    department_a, _ = _dept_and_position(admin_client, "mismatcha")
    _, position_b = _dept_and_position(admin_client, "mismatchb")

    response = _create_employee(admin_client, department_a, position_b)
    assert response.status_code == 400


def test_rib_and_salary_never_leak_outside_html_detail(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "secrets")
    plaintext_rib = "2" * 24
    created = _create_employee(
        admin_client, department_id, position_id, rib=plaintext_rib, gross_salary=12345.67
    ).json()

    html_response = admin_client.get(f"/employees/{created['id']}")
    assert plaintext_rib in html_response.text

    list_response = admin_client.get("/employees", headers=JSON_HEADERS)
    assert plaintext_rib not in list_response.text

    csv_response = admin_client.get("/employees/export")
    assert plaintext_rib not in csv_response.text
    header_row = csv_response.text.splitlines()[0].lower()
    assert "salary" not in header_row
    assert "rib" not in header_row


def test_csv_export_content_type_and_columns(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "csvcols")
    _create_employee(admin_client, department_id, position_id)

    response = admin_client.get("/employees/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    header_row = response.text.splitlines()[0]
    assert "matricule" in header_row


def test_search_and_department_filter(admin_client):
    department_a, position_a = _dept_and_position(admin_client, "deptsearcha")
    department_b, position_b = _dept_and_position(admin_client, "deptsearchb")
    _create_employee(admin_client, department_a, position_a, last_name="Zidane", first_name="Karim")
    _create_employee(admin_client, department_b, position_b, last_name="Amrani", first_name="Sara")

    search_response = admin_client.get("/employees?search=zidane", headers=JSON_HEADERS)
    names = [e["last_name"] for e in search_response.json()]
    assert names == ["Zidane"]

    department_response = admin_client.get(
        f"/employees?department_id={department_b}", headers=JSON_HEADERS
    )
    names = [e["last_name"] for e in department_response.json()]
    assert names == ["Amrani"]


def test_pagination_respects_limit(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "pagination")
    for name in ["Alami", "Bennis", "Chraibi"]:
        _create_employee(admin_client, department_id, position_id, last_name=name)

    response = admin_client.get(
        f"/employees?department_id={department_id}&limit=10", headers=JSON_HEADERS
    )
    names = [e["last_name"] for e in response.json()]
    assert names == ["Alami", "Bennis", "Chraibi"]


def test_list_employees_requires_authentication(client):
    response = client.get("/employees", headers=JSON_HEADERS)
    assert response.status_code == 401


def test_list_employees_rejects_non_admin(employee_client):
    response = employee_client.get("/employees", headers=JSON_HEADERS)
    assert response.status_code == 403


def test_update_employee_changes_fields_but_not_matricule(admin_client):
    department_id, position_id = _dept_and_position(admin_client, "update")
    created = _create_employee(admin_client, department_id, position_id).json()

    update_payload = _valid_employee_payload(department_id, position_id, last_name="Nouveaunom")
    del update_payload["department_id"]
    del update_payload["position_id"]

    response = admin_client.post(
        f"/employees/{created['id']}", json=update_payload, headers=JSON_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["last_name"] == "Nouveaunom"
    assert body["matricule"] == created["matricule"]
