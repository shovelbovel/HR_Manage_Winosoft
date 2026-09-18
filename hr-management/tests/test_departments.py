from app.repositories.departments_repository import DepartmentsRepository

JSON_HEADERS = {"accept": "application/json"}


def _create(client, code: str, name: str):
    return client.post("/departments", json={"code": code, "name": name}, headers=JSON_HEADERS)


def test_create_department_success_and_normalizes_code(admin_client):
    response = _create(admin_client, "it", "Informatique")
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "IT"
    assert body["name"] == "Informatique"
    assert body["employee_count"] == 0


def test_create_department_duplicate_code_conflict(admin_client):
    _create(admin_client, "IT", "Informatique")
    response = _create(admin_client, "it", "Informatique Bis")
    assert response.status_code == 409


def test_list_departments_requires_authentication(client):
    response = client.get("/departments", headers=JSON_HEADERS)
    assert response.status_code == 401


def test_list_departments_rejects_non_admin(employee_client):
    response = employee_client.get("/departments", headers=JSON_HEADERS)
    assert response.status_code == 403


def test_create_department_rejects_non_admin(employee_client):
    response = _create(employee_client, "IT", "Informatique")
    assert response.status_code == 403


def test_rename_department_leaves_code_untouched(admin_client):
    created = _create(admin_client, "HR", "Ressources Humaines").json()

    response = admin_client.post(
        f"/departments/{created['id']}", json={"name": "RH"}, headers=JSON_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "RH"
    assert body["code"] == "HR"


def test_delete_empty_department_succeeds(admin_client):
    created = _create(admin_client, "FIN", "Finance").json()

    delete_response = admin_client.post(
        f"/departments/{created['id']}/delete", headers=JSON_HEADERS
    )
    assert delete_response.status_code == 200

    get_response = admin_client.get(f"/departments/{created['id']}", headers=JSON_HEADERS)
    assert get_response.status_code == 404


def test_delete_occupied_department_is_blocked(admin_client, db):
    created = _create(admin_client, "OPS", "Opérations").json()
    DepartmentsRepository(db).increment_employee_count(created["id"], delta=1)

    delete_response = admin_client.post(
        f"/departments/{created['id']}/delete", headers=JSON_HEADERS
    )
    assert delete_response.status_code == 409

    get_response = admin_client.get(f"/departments/{created['id']}", headers=JSON_HEADERS)
    assert get_response.status_code == 200


def test_list_departments_ordered_by_name(admin_client):
    _create(admin_client, "ZZZ", "Zoologie")
    _create(admin_client, "AAA", "Achats")

    response = admin_client.get("/departments", headers=JSON_HEADERS)
    assert response.status_code == 200
    names = [department["name"] for department in response.json()]
    assert names == sorted(names)
    assert {"Achats", "Zoologie"} <= set(names)


def test_create_department_malformed_json_returns_400_not_500(admin_client):
    # Regression test for app.core.http.read_body, shared by every router:
    # a syntactically broken JSON body must 400, never crash with a 500.
    response = admin_client.post(
        "/departments",
        content=b"{not valid json",
        headers={**JSON_HEADERS, "content-type": "application/json"},
    )
    assert response.status_code == 400


def test_create_department_non_utf8_body_returns_400_not_500(admin_client):
    # Regression test: a body that isn't valid UTF-8 (e.g. Latin-1 encoded
    # accented characters from a mis-configured client) must 400, not crash
    # the process with an unhandled UnicodeDecodeError.
    response = admin_client.post(
        "/departments",
        content='{"code": "OP", "name": "Opérations"}'.encode("latin-1"),
        headers={**JSON_HEADERS, "content-type": "application/json"},
    )
    assert response.status_code == 400
