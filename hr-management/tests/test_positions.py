from app.repositories.positions_repository import PositionsRepository

JSON_HEADERS = {"accept": "application/json"}


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


def test_create_position_success(admin_client):
    department_id = _create_department(admin_client, "IT", "Informatique")
    response = _create_position(admin_client, department_id, "Développeur")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Développeur"
    assert body["department_id"] == department_id
    assert body["department_name"] == "Informatique"
    assert body["occupant_count"] == 0
    assert body["max_occupants"] is None


def test_create_position_unknown_department_404(admin_client):
    response = _create_position(admin_client, "does-not-exist", "Développeur")
    assert response.status_code == 404


def test_list_positions_filters_by_department(admin_client):
    dept_a = _create_department(admin_client, "AAA", "Département A")
    dept_b = _create_department(admin_client, "BBB", "Département B")
    _create_position(admin_client, dept_a, "Poste A1")
    _create_position(admin_client, dept_b, "Poste B1")

    response = admin_client.get(f"/positions?department_id={dept_a}", headers=JSON_HEADERS)
    assert response.status_code == 200
    titles = [position["title"] for position in response.json()]
    assert titles == ["Poste A1"]


def test_update_position_leaves_department_untouched(admin_client):
    department_id = _create_department(admin_client, "HR", "Ressources Humaines")
    created = _create_position(admin_client, department_id, "Chargé RH").json()

    response = admin_client.post(
        f"/positions/{created['id']}", json={"title": "Responsable RH"}, headers=JSON_HEADERS
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Responsable RH"
    assert body["department_id"] == department_id


def test_delete_empty_position_succeeds(admin_client):
    department_id = _create_department(admin_client, "FIN", "Finance")
    created = _create_position(admin_client, department_id, "Comptable").json()

    delete_response = admin_client.post(f"/positions/{created['id']}/delete", headers=JSON_HEADERS)
    assert delete_response.status_code == 200

    get_response = admin_client.get(f"/positions/{created['id']}", headers=JSON_HEADERS)
    assert get_response.status_code == 404


def test_delete_occupied_position_is_blocked(admin_client, db):
    department_id = _create_department(admin_client, "OPS", "Opérations")
    created = _create_position(admin_client, department_id, "Technicien").json()
    PositionsRepository(db).increment_occupant_count(created["id"], delta=1)

    delete_response = admin_client.post(f"/positions/{created['id']}/delete", headers=JSON_HEADERS)
    assert delete_response.status_code == 409

    get_response = admin_client.get(f"/positions/{created['id']}", headers=JSON_HEADERS)
    assert get_response.status_code == 200


def test_list_positions_requires_authentication(client):
    response = client.get("/positions", headers=JSON_HEADERS)
    assert response.status_code == 401


def test_list_positions_rejects_non_admin(employee_client):
    response = employee_client.get("/positions", headers=JSON_HEADERS)
    assert response.status_code == 403
