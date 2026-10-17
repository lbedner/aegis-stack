"""The whole system model as JSON (``GET /api/v1/ontology``): admins only,
open on a stack without auth, as every operator route is."""

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.ontology import SCHEMA_VERSION
from app.services.shared.deps import get_admin_actor
from tests._audit import as_admin

URL = "/api/v1/ontology"


def test_an_admin_gets_the_whole_model(client: TestClient) -> None:
    response = as_admin(client).get(URL)
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert any(n["id"] == "component:backend" for n in body["nodes"])


def test_anyone_else_is_refused(client: TestClient) -> None:
    def refused() -> None:
        raise HTTPException(status_code=403)

    client.app.dependency_overrides[get_admin_actor] = refused
    assert client.get(URL).status_code == 403
