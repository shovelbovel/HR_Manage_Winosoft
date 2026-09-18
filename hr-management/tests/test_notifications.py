import pytest

from app.models import LeaveDocument, LeaveStatus
from app.repositories.leave_types_repository import LeaveTypesRepository
from app.repositories.notifications_repository import NotificationsRepository
from app.repositories.users_repository import UsersRepository
from app.services.notifications_service import NotificationsService
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
        "cin": f"AB{300000 + n}",
        "birth_date": "1990-05-15",
        "professional_email": f"notif-employee{n}@hr-management-test.dev",
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


def _recent(client) -> dict:
    response = client.get("/notifications/recent", headers=JSON_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _find(notifications: list[dict], category: str, link: str) -> dict | None:
    for notification in notifications:
        if notification["category"] == category and notification["link"] == link:
            return notification
    return None


def test_leave_submission_notifies_department_manager_and_admin_only(
    admin_client, make_manager_client, make_employee_linked_client, seeded_reference_data, db
):
    department_id = _create_department(admin_client, "NOTIFDEPTA", "Dept A")
    position_id = _create_position(admin_client, department_id, "Poste A")
    other_department_id = _create_department(admin_client, "NOTIFDEPTB", "Dept B")

    employee = _create_employee(admin_client, department_id, position_id)
    employee_client = make_employee_linked_client(
        employee["id"], email="notif-linked1@hr-management-test.dev"
    )
    manager_a = make_manager_client(department_id, email="notif-managera@hr-management-test.dev")
    manager_b = make_manager_client(other_department_id, email="notif-managerb@hr-management-test.dev")

    leave_type_id = _leave_type_id(db, "ANNUAL")
    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-01-05", "end_date": "2026-01-06"},
        headers=JSON_HEADERS,
    ).json()
    link = f"/leaves/{leave['id']}"

    admin_hit = _find(_recent(admin_client)["notifications"], "leave_pending", link)
    manager_a_hit = _find(_recent(manager_a)["notifications"], "leave_pending", link)
    manager_b_hit = _find(_recent(manager_b)["notifications"], "leave_pending", link)

    assert admin_hit is not None
    assert manager_a_hit is not None
    assert manager_b_hit is None


def test_leave_decision_notifies_only_the_linked_employee(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    department_id = _create_department(admin_client, "NOTIFDEPTC", "Dept C")
    position_id = _create_position(admin_client, department_id, "Poste C")
    employee = _create_employee(admin_client, department_id, position_id)
    employee_client = make_employee_linked_client(
        employee["id"], email="notif-linked2@hr-management-test.dev"
    )
    leave_type_id = _leave_type_id(db, "ANNUAL")

    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-02-02", "end_date": "2026-02-03"},
        headers=JSON_HEADERS,
    ).json()
    admin_client.post(f"/leaves/{leave['id']}/approve", headers=JSON_HEADERS)

    link = f"/leaves/{leave['id']}"
    hit = _find(_recent(employee_client)["notifications"], "leave_decision", link)
    assert hit is not None
    assert "approuvée" in hit["message"]


def test_leave_rejection_notifies_employee_with_refused_wording(
    admin_client, make_employee_linked_client, seeded_reference_data, db
):
    department_id = _create_department(admin_client, "NOTIFDEPTD", "Dept D")
    position_id = _create_position(admin_client, department_id, "Poste D")
    employee = _create_employee(admin_client, department_id, position_id)
    employee_client = make_employee_linked_client(
        employee["id"], email="notif-linked3@hr-management-test.dev"
    )
    leave_type_id = _leave_type_id(db, "ANNUAL")

    leave = employee_client.post(
        "/leaves",
        json={"leave_type_id": leave_type_id, "start_date": "2026-03-02", "end_date": "2026-03-03"},
        headers=JSON_HEADERS,
    ).json()
    admin_client.post(
        f"/leaves/{leave['id']}/reject", json={"reason": "Non"}, headers=JSON_HEADERS
    )

    link = f"/leaves/{leave['id']}"
    hit = _find(_recent(employee_client)["notifications"], "leave_decision", link)
    assert hit is not None
    assert "refusée" in hit["message"]


def test_leave_decision_with_no_linked_account_does_not_raise(db):
    # Not reachable through the router today (submitting a leave already
    # requires a linked account) — this exercises the defensive guard
    # directly, same as any other codepath that can't be driven via HTTP.
    service = NotificationsService(NotificationsRepository(db), UsersRepository(db))
    orphan_leave = LeaveDocument(
        id="orphan-leave",
        employee_id="no-such-employee",
        employee_name="Personne",
        department_id="no-such-department",
        leave_type_id="lt1",
        leave_type_name="Congé annuel",
        start_date="2026-01-01T00:00:00Z",
        end_date="2026-01-02T00:00:00Z",
        working_days=1,
        status=LeaveStatus.APPROVED,
        requested_at="2026-01-01T00:00:00Z",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    service.notify_leave_decided(orphan_leave)  # must not raise


def test_new_employee_notifies_department_manager_and_admin_only(
    admin_client, make_manager_client
):
    department_id = _create_department(admin_client, "NOTIFDEPTE", "Dept E")
    position_id = _create_position(admin_client, department_id, "Poste E")
    other_department_id = _create_department(admin_client, "NOTIFDEPTF", "Dept F")

    manager_a = make_manager_client(department_id, email="notif-managere@hr-management-test.dev")
    manager_b = make_manager_client(
        other_department_id, email="notif-managerf@hr-management-test.dev"
    )

    employee = _create_employee(admin_client, department_id, position_id)
    link = f"/employees/{employee['id']}"

    admin_hit = _find(_recent(admin_client)["notifications"], "new_employee", link)
    manager_a_hit = _find(_recent(manager_a)["notifications"], "new_employee", link)
    manager_b_hit = _find(_recent(manager_b)["notifications"], "new_employee", link)

    assert admin_hit is not None
    assert manager_a_hit is not None
    assert manager_b_hit is None


def test_recent_endpoint_scoped_to_caller(admin_client, make_manager_client):
    department_id = _create_department(admin_client, "NOTIFDEPTG", "Dept G")
    position_id = _create_position(admin_client, department_id, "Poste G")
    _create_employee(admin_client, department_id, position_id)
    bystander = make_manager_client(
        "nonexistent-department", email="notif-bystander@hr-management-test.dev"
    )
    # An unrelated manager (no department overlap with anything created)
    # starts with an empty inbox, even though the admin's own inbox just
    # gained a new_employee notification from the setup above.
    body = _recent(bystander)
    assert body["unread_count"] == 0
    assert body["notifications"] == []


def test_mark_read_flips_state_and_rejects_other_users_notification(
    admin_client, make_employee_linked_client
):
    department_id = _create_department(admin_client, "NOTIFDEPTH", "Dept H")
    position_id = _create_position(admin_client, department_id, "Poste H")
    employee = _create_employee(admin_client, department_id, position_id)
    owner_client = make_employee_linked_client(
        employee["id"], email="notif-owner@hr-management-test.dev"
    )

    other_employee = _create_employee(admin_client, department_id, position_id)
    other_client = make_employee_linked_client(
        other_employee["id"], email="notif-other@hr-management-test.dev"
    )

    admin_hit = _find(
        _recent(admin_client)["notifications"], "new_employee", f"/employees/{employee['id']}"
    )
    assert admin_hit is not None

    # Neither the owning employee nor an unrelated employee can act on an
    # admin-owned notification — 404, never 403.
    forbidden = owner_client.post(
        f"/notifications/{admin_hit['id']}/read", headers=JSON_HEADERS
    )
    assert forbidden.status_code == 404
    forbidden_other = other_client.post(
        f"/notifications/{admin_hit['id']}/read", headers=JSON_HEADERS
    )
    assert forbidden_other.status_code == 404

    missing = admin_client.post("/notifications/does-not-exist/read", headers=JSON_HEADERS)
    assert missing.status_code == 404

    success = admin_client.post(f"/notifications/{admin_hit['id']}/read", headers=JSON_HEADERS)
    assert success.status_code == 200
    assert success.json()["is_read"] is True


def test_mark_all_read_zeroes_unread_count(admin_client):
    department_id = _create_department(admin_client, "NOTIFDEPTI", "Dept I")
    position_id = _create_position(admin_client, department_id, "Poste I")
    _create_employee(admin_client, department_id, position_id)
    _create_employee(admin_client, department_id, position_id)

    assert _recent(admin_client)["unread_count"] >= 2

    response = admin_client.post("/notifications/mark-all-read", headers=JSON_HEADERS)
    assert response.status_code == 200

    assert _recent(admin_client)["unread_count"] == 0


def test_list_notifications_requires_authentication(client):
    response = client.get("/notifications", headers=JSON_HEADERS)
    assert response.status_code == 401


def test_list_notifications_accessible_to_employee_role(employee_client):
    response = employee_client.get("/notifications", headers=JSON_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


def test_list_notifications_paginates_by_cursor(admin_client):
    department_id = _create_department(admin_client, "NOTIFDEPTJ", "Dept J")
    position_id = _create_position(admin_client, department_id, "Poste J")
    for _ in range(3):
        _create_employee(admin_client, department_id, position_id)

    first_page = admin_client.get("/notifications?limit=2", headers=JSON_HEADERS).json()
    assert len(first_page) == 2

    second_page = admin_client.get(
        f"/notifications?limit=2&cursor={first_page[-1]['id']}", headers=JSON_HEADERS
    ).json()
    assert len(second_page) == 1
    assert second_page[0]["id"] != first_page[0]["id"]
    assert second_page[0]["id"] != first_page[1]["id"]
