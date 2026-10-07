"""Research over HTTP (#1422): a watch is saved, refreshed and read back
through the API, scoped to the caller. Through ``authenticated_app_client``
so the suite runs with and without the auth service."""

from fastapi.testclient import TestClient
import pytest

from tests._research import FakeSite, comment, story

# Each test saves a watch, refreshes it and reads it back: the same reads
# repeat across the steps by construction.
pytestmark = pytest.mark.queryspy(allow_n_plus_one=True)


def _watch(client: TestClient, q: str, **extra: object) -> int:
    response = client.post(
        "/api/v1/research/watches",
        json={"source": "fake", "name": q, "query": {"q": q}, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_a_watch_is_saved_refreshed_and_read_back(
    authenticated_app_client: TestClient, site: FakeSite
) -> None:
    client = authenticated_app_client
    site.results["fastapi"] = [story("1", "A FastAPI template", score=42)]
    watch_id = _watch(client, "fastapi")

    refreshed = client.post(f"/api/v1/research/watches/{watch_id}/refresh")
    items = client.get("/api/v1/research/items", params={"text": "template"})

    assert refreshed.json() == {"found": 1}
    (item,) = items.json()
    assert item["title"] == "A FastAPI template" and item["score"] == 42
    assert [w["id"] for w in client.get("/api/v1/research/watches").json()] == [
        watch_id
    ]


def test_a_thread_reads_back_top_first(
    authenticated_app_client: TestClient, site: FakeSite
) -> None:
    client = authenticated_app_client
    site.results["t"] = [story("1", "Launch")]
    site.threads["1"] = [story("1", "Launch"), comment("2", "1", "Nice.")]
    watch_id = _watch(client, "t", with_threads=True)
    client.post(f"/api/v1/research/watches/{watch_id}/refresh")
    top = client.get("/api/v1/research/items", params={"kind": "story"}).json()[0]

    thread = client.get(f"/api/v1/research/items/{top['id']}/thread").json()

    assert [i["external_id"] for i in thread] == ["1", "2"]


def test_an_items_history_reads_back_a_day_at_a_time(
    authenticated_app_client: TestClient, site: FakeSite
) -> None:
    client = authenticated_app_client
    site.results["h"] = [story("7", "Took off", score=42)]
    watch_id = _watch(client, "h")
    client.post(f"/api/v1/research/watches/{watch_id}/refresh")
    (item,) = client.get("/api/v1/research/items", params={"text": "Took off"}).json()

    history = client.get(f"/api/v1/research/items/{item['id']}/history").json()

    assert [(h["score"], h["comment_count"]) for h in history] == [(42, 0)]


def test_a_query_the_source_refuses_is_a_400(
    authenticated_app_client: TestClient, site: FakeSite
) -> None:
    response = authenticated_app_client.post(
        "/api/v1/research/watches",
        json={"source": "fake", "name": "typo", "query": {"query": "x"}},
    )

    assert response.status_code == 400


def test_an_unknown_watch_is_a_404(authenticated_app_client: TestClient) -> None:
    client = authenticated_app_client

    assert client.post("/api/v1/research/watches/999/refresh").status_code == 404
    assert client.delete("/api/v1/research/watches/999").status_code == 404


def test_installed_sources_are_listed(
    authenticated_app_client: TestClient, site: FakeSite
) -> None:
    sources = authenticated_app_client.get("/api/v1/research/sources").json()

    assert {"name": "fake", "title": "Fake"} in sources


def test_a_source_that_fails_says_so(
    authenticated_app_client: TestClient, site: FakeSite
) -> None:
    site.failing.add("boom")
    watch_id = _watch(authenticated_app_client, "boom")

    response = authenticated_app_client.post(
        f"/api/v1/research/watches/{watch_id}/refresh"
    )

    assert response.status_code == 502
    assert "failed" in response.json()["detail"]
