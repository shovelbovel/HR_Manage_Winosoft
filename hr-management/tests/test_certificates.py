import re

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


def _employee_payload(department_id: str, position_id: str, **overrides) -> dict:
    _UNIQUE_COUNTER["value"] += 1
    n = _UNIQUE_COUNTER["value"]
    payload = {
        "first_name": "Jean",
        "last_name": "Dupont",
        "cin": f"AB{400000 + n}",
        "birth_date": "1990-05-15",
        "professional_email": f"cert-employee{n}@hr-management-test.dev",
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


def _create_employee(client, department_id: str, position_id: str, **overrides) -> dict:
    payload = _employee_payload(department_id, position_id, **overrides)
    response = client.post("/employees", json=payload, headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _generate(client, **body):
    return client.post("/certificates", json=body, headers=JSON_HEADERS)


def test_certificate_numbers_are_sequential(admin_client):
    department_id = _create_department(admin_client, "CERTNUM", "Dept Num")
    position_id = _create_position(admin_client, department_id, "Poste")
    employee = _create_employee(admin_client, department_id, position_id)

    first = _generate(admin_client, certificate_type="work", employee_id=employee["id"]).json()
    second = _generate(admin_client, certificate_type="work", employee_id=employee["id"]).json()

    assert re.match(r"^ATT-\d{4}-\d{4}$", first["number"])
    assert re.match(r"^ATT-\d{4}-\d{4}$", second["number"])
    assert first["number"] != second["number"]


def test_salary_certificate_snapshot_survives_later_salary_edit(admin_client):
    department_id = _create_department(admin_client, "CERTFID", "Dept Fidelite")
    position_id = _create_position(admin_client, department_id, "Poste")
    employee = _create_employee(admin_client, department_id, position_id, gross_salary=8000)

    certificate = _generate(
        admin_client, certificate_type="salary", employee_id=employee["id"], net_salary=7000
    ).json()
    assert certificate["data_snapshot"]["gross_salary"] == 8000

    update_payload = _employee_payload(department_id, position_id, gross_salary=9500)
    del update_payload["department_id"]
    del update_payload["position_id"]
    update_response = admin_client.post(
        f"/employees/{employee['id']}", json=update_payload, headers=JSON_HEADERS
    )
    assert update_response.status_code == 200, update_response.text

    reread = admin_client.get(f"/certificates/{certificate['id']}", headers=JSON_HEADERS).json()
    assert reread["data_snapshot"]["gross_salary"] == 8000  # frozen, not 9500

    download = admin_client.get(f"/certificates/{certificate['id']}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content.startswith(b"%PDF")


def test_manager_and_employee_forbidden_from_admin_only_types(
    admin_client, make_manager_client, make_employee_linked_client
):
    department_id = _create_department(admin_client, "CERTADMIN", "Dept AdminOnly")
    position_id = _create_position(admin_client, department_id, "Poste")
    employee = _create_employee(admin_client, department_id, position_id)
    manager = make_manager_client(department_id, email="cert-manager1@hr-management-test.dev")
    employee_client = make_employee_linked_client(
        employee["id"], email="cert-linked1@hr-management-test.dev"
    )

    for certificate_type in ("salary", "end_of_contract"):
        manager_response = _generate(
            manager, certificate_type=certificate_type, employee_id=employee["id"], net_salary=1000
        )
        assert manager_response.status_code == 403

        employee_response = _generate(
            employee_client,
            certificate_type=certificate_type,
            employee_id=employee["id"],
            net_salary=1000,
        )
        assert employee_response.status_code == 403


def test_employee_generating_for_someone_else_gets_404(
    admin_client, make_employee_linked_client
):
    department_id = _create_department(admin_client, "CERTSCOPE", "Dept Scope")
    position_id = _create_position(admin_client, department_id, "Poste")
    employee_a = _create_employee(admin_client, department_id, position_id)
    employee_b = _create_employee(admin_client, department_id, position_id)
    client_a = make_employee_linked_client(
        employee_a["id"], email="cert-linkeda@hr-management-test.dev"
    )

    response = _generate(client_a, certificate_type="work", employee_id=employee_b["id"])
    assert response.status_code == 404


def test_manager_scoped_to_own_department(admin_client, make_manager_client):
    department_a = _create_department(admin_client, "CERTDEPTA", "Dept A")
    position_a = _create_position(admin_client, department_a, "Poste A")
    department_b = _create_department(admin_client, "CERTDEPTB", "Dept B")
    position_b = _create_position(admin_client, department_b, "Poste B")

    employee_a = _create_employee(admin_client, department_a, position_a)
    employee_b = _create_employee(admin_client, department_b, position_b)
    manager_a = make_manager_client(department_a, email="cert-managera@hr-management-test.dev")

    ok = _generate(manager_a, certificate_type="work", employee_id=employee_a["id"])
    assert ok.status_code == 200

    forbidden = _generate(manager_a, certificate_type="work", employee_id=employee_b["id"])
    assert forbidden.status_code == 404

    certificate_id = ok.json()["id"]
    view_own = manager_a.get(f"/certificates/{certificate_id}", headers=JSON_HEADERS)
    assert view_own.status_code == 200


def test_leave_certificate_requires_approved_leave(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    department_id = _create_department(admin_client, "CERTLEAVE", "Dept Leave")
    position_id = _create_position(admin_client, department_id, "Poste")
    employee = _create_employee(admin_client, department_id, position_id)
    employee_client = make_employee_linked_client(
        employee["id"], email="cert-leaveemp@hr-management-test.dev"
    )
    leave_type_id = _leave_type_id(db, "ANNUAL")

    pending_leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-01-05", "end_date": "2026-01-06"},
        headers=JSON_HEADERS,
    ).json()

    rejected = _generate(
        admin_client,
        certificate_type="leave",
        employee_id=employee["id"],
        leave_id=pending_leave["id"],
    )
    assert rejected.status_code == 409

    admin_client.post(f"/leaves/{pending_leave['id']}/approve", headers=JSON_HEADERS)
    approved = _generate(
        admin_client,
        certificate_type="leave",
        employee_id=employee["id"],
        leave_id=pending_leave["id"],
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data_snapshot"]["leave_type_name"]


def test_internship_certificate_requires_stage_contract(admin_client):
    department_id = _create_department(admin_client, "CERTSTAGE", "Dept Stage")
    position_id = _create_position(admin_client, department_id, "Poste")
    employee = _create_employee(admin_client, department_id, position_id)  # CDI, not STAGE

    response = _generate(
        admin_client,
        certificate_type="internship",
        employee_id=employee["id"],
        internship_subject="Développement web",
    )
    assert response.status_code == 400


def test_certificates_list_scoping_and_role_gate(
    admin_client, make_manager_client, make_employee_linked_client
):
    department_a = _create_department(admin_client, "CERTLISTA", "Dept ListA")
    position_a = _create_position(admin_client, department_a, "Poste A")
    department_b = _create_department(admin_client, "CERTLISTB", "Dept ListB")
    position_b = _create_position(admin_client, department_b, "Poste B")

    employee_a = _create_employee(admin_client, department_a, position_a)
    employee_b = _create_employee(admin_client, department_b, position_b)
    employee_client_a = make_employee_linked_client(
        employee_a["id"], email="cert-listlinked@hr-management-test.dev"
    )
    manager_a = make_manager_client(department_a, email="cert-listmanager@hr-management-test.dev")

    cert_a = _generate(admin_client, certificate_type="work", employee_id=employee_a["id"]).json()
    _generate(admin_client, certificate_type="work", employee_id=employee_b["id"])

    admin_list = admin_client.get("/certificates", headers=JSON_HEADERS).json()
    admin_ids = {c["id"] for c in admin_list}
    assert cert_a["id"] in admin_ids
    assert len(admin_list) >= 2

    manager_list = manager_a.get("/certificates", headers=JSON_HEADERS).json()
    manager_ids = {c["id"] for c in manager_list}
    assert cert_a["id"] in manager_ids
    assert all(c["department_id"] == department_a for c in manager_list)

    employee_forbidden = employee_client_a.get("/certificates", headers=JSON_HEADERS)
    assert employee_forbidden.status_code == 403

    my_certificates = employee_client_a.get("/certificates/my", headers=JSON_HEADERS).json()
    assert {c["id"] for c in my_certificates} == {cert_a["id"]}


def test_certificates_require_authentication(client):
    response = client.get("/certificates/my", headers=JSON_HEADERS)
    assert response.status_code == 401
