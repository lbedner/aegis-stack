"""Overseer > Deployments > DNS: the records on the project's domain, read
and changed through its registrar (``app.services.ops.dns``), as the
``dns`` CLI does; every change audited."""

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.components.web_frontend import overseer_deploy_actions as actions
from app.core import exposure
from app.core.config import settings
from app.services.ops import dns
from app.services.ops.types import CreatedRecord, DnsRecord, RetrievedRecord
from app.services.system import hosting
from tests._audit import recording
from tests._secret_settings import FakeStore, use_store
from tests.web.dom import location, one, select, table_rows, text, triggers
from tests.web.overseer import page_html, sign_in, status_with

PAGE = f"{actions.PAGE}/dns"
RECORDS = f"{actions.PARTIALS}/dns/records"
SERVER = "203.0.113.7"
KEYS = {name: f"{name.lower()}-test" for name in dns.PROVIDER.keys}


class FakeRegistrar:
    """The registrar, keeping its records in a list."""

    name = "porkbun"

    def __init__(self, *records: RetrievedRecord) -> None:
        self.records = list(records)

    async def list_dns_records(self, domain: str) -> list[RetrievedRecord]:
        return list(self.records)

    async def create_dns_records(
        self, domain: str, records: list[DnsRecord]
    ) -> list[CreatedRecord]:
        made = []
        for r in records:
            found = RetrievedRecord(
                provider_id=str(100 + len(self.records)),
                host=r.host,
                type=r.type,
                value=r.value,
                ttl=r.ttl,
                priority=r.priority,
            )
            self.records.append(found)
            made.append(CreatedRecord(r, found.provider_id, datetime.now(UTC)))
        return made

    async def edit_dns_record(
        self, domain: str, provider_id: str, record: DnsRecord
    ) -> None:
        self.records = [
            RetrievedRecord(
                provider_id,
                record.host,
                record.type,
                record.value,
                record.ttl,
                record.priority,
            )
            if r.provider_id == provider_id
            else r
            for r in self.records
        ]

    async def delete_dns_record(self, domain: str, provider_id: str) -> None:
        self.records = [r for r in self.records if r.provider_id != provider_id]


APEX = RetrievedRecord(provider_id="1", host="", type="A", value=SERVER, ttl=600)
WWW = RetrievedRecord(provider_id="2", host="www", type="A", value=SERVER, ttl=600)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """No Porkbun keys in ``.env``; a secrets store holding them."""
    for name in KEYS:
        monkeypatch.setitem(settings.__dict__, name, None)
    found = use_store(monkeypatch)
    found.values.update(KEYS)
    return found


@pytest.fixture
def registrar(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, store: FakeStore
) -> FakeRegistrar:
    """The dev build, on example.com, deploying to ``SERVER``."""
    sign_in(app, monkeypatch, status_with())
    monkeypatch.setattr(settings, "BUILD_ID", exposure.LOCAL)
    monkeypatch.setattr(settings, "BASE_DOMAIN", "Example.com")
    server = {"server": {"host": SERVER, "user": "root", "path": "/opt/app"}}
    monkeypatch.setattr(hosting, "deploy_config", lambda *_: server)
    fake = FakeRegistrar(APEX, WWW)
    monkeypatch.setattr(dns, "registrar", lambda: fake)
    return fake


def _rows(client: TestClient) -> list[dict[str, Any]]:
    return table_rows(page_html(client, PAGE), "#deployments-dns table")


def test_dns_is_a_deployments_section(registrar: FakeRegistrar, app: FastAPI) -> None:
    html = page_html(TestClient(app), actions.PAGE)
    assert text(one(html, f'a[href="{PAGE}"]')) == "DNS"


def test_lists_the_domains_records(registrar: FakeRegistrar, app: FastAPI) -> None:
    rows = _rows(TestClient(app))
    assert [
        {k: text(v) for k, v in row.items() if k in ("Type", "Host", "Value", "TTL")}
        for row in rows
    ] == [
        {"Type": "A", "Host": "@", "Value": SERVER, "TTL": "600"},
        {"Type": "A", "Host": "www", "Value": SERVER, "TTL": "600"},
    ]


def test_a_deployed_server_manages_its_records_too(
    registrar: FakeRegistrar, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The records live at the registrar, not with the deploy agent, so a
    deployed build reads and changes them as the dev build does."""
    monkeypatch.setattr(settings, "BUILD_ID", "deployed-build")
    html = page_html(TestClient(app), PAGE)
    hosts = [text(row["Host"]) for row in table_rows(html, "#deployments-dns table")]
    assert hosts == ["@", "www"]
    add = one(html, f'#overseer-main header [hx-get="{RECORDS}/new"]')
    assert text(add) == "Add record"


def test_the_card_names_where_the_records_live(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    """Its registrar, by logo and name, as Settings shows a provider."""
    header = one(page_html(TestClient(app), PAGE), "#deployments-dns header")
    assert one(header, "img").get("src") == dns.PROVIDER.logo
    assert text(header) == "example.com Porkbun"


def test_a_rows_changes_wait_behind_its_menu(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    """Edit and Delete are a row's rarer actions: behind its "...", not a
    button on every row."""
    actions_cell = _rows(TestClient(app))[1]["Actions"]
    menu = one(actions_cell, "details[data-dropdown]")
    items = {text(b): b.get("hx-get") for b in select(menu, "[role=menu] button")}
    assert items == {
        "Edit": f"{RECORDS}/2/edit",
        "Delete": f"{RECORDS}/2/confirm-delete",
    }


def test_add_and_edit_are_one_form(registrar: FakeRegistrar, app: FastAPI) -> None:
    """A new record's dialog and a record's Edit are the same form: the
    new one empty, an A record's IP the server's unless typed; the edit
    holding what the record has."""
    client = TestClient(app)
    html = page_html(client, PAGE)
    add = one(html, f'#overseer-main header [hx-get="{RECORDS}/new"]')
    assert text(add) == "Add record"
    new = client.get(f"{RECORDS}/new").text
    assert one(new, "form").get("hx-post") == RECORDS
    assert one(new, "input[name=value]").get("placeholder") == SERVER
    edit = client.get(f"{RECORDS}/2/edit").text
    assert one(edit, "form").get("hx-post") == f"{RECORDS}/2"
    assert one(edit, "input[name=host]").get("value") == "www"
    assert one(edit, "select[name=type] option[selected]").get("value") == "A"
    assert one(edit, "input[name=value]").get("value") == SERVER
    assert client.get(f"{RECORDS}/9/edit").status_code == 404


def test_an_a_record_points_at_the_server_unless_told(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    client = TestClient(app)
    audit = recording(client)
    response = client.post(RECORDS, data={"host": "Overseer", "type": "A"})
    assert location(response) == PAGE
    assert triggers(response)["toast"]["text"] == (
        f"Added A overseer.example.com → {SERVER}"
    )
    added = registrar.records[-1]
    assert (added.host, added.type, added.value) == ("overseer", "A", SERVER)
    (event,) = audit.events
    assert (event["event_type"], event["outcome"]) == ("deploy.dns_set", "requested")
    client.post(RECORDS, data={"host": "cdn", "type": "cname", "value": "x.net"})
    assert (registrar.records[-1].type, registrar.records[-1].value) == (
        "CNAME",
        "x.net",
    )


def test_a_deployed_server_points_an_a_record_at_itself(
    registrar: FakeRegistrar, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server has no ``.aegis/deploy.yml``: its address is the one the
    deploy stamped (``SERVER_HOST``)."""
    monkeypatch.setattr(hosting, "deploy_config", lambda *_: {})
    monkeypatch.setattr(settings, "SERVER_HOST", "198.51.100.4")
    client = TestClient(app)
    new = client.get(f"{RECORDS}/new").text
    assert one(new, "input[name=value]").get("placeholder") == "198.51.100.4"
    client.post(RECORDS, data={"host": "overseer", "type": "A"})
    assert registrar.records[-1].value == "198.51.100.4"


def test_an_edit_changes_the_record_in_place(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    """Re-pointing a record keeps it (its id): no moment without it, as a
    delete and an add would leave."""
    client = TestClient(app)
    audit = recording(client)
    form = {"host": "www", "type": "A", "value": "198.51.100.9"}
    response = client.post(f"{RECORDS}/2", data=form)
    assert location(response) == PAGE
    assert triggers(response)["toast"]["text"] == (
        "Changed A www.example.com → 198.51.100.9"
    )
    assert [(r.provider_id, r.value) for r in registrar.records] == [
        ("1", SERVER),
        ("2", "198.51.100.9"),
    ]
    (event,) = audit.events
    assert (event["event_type"], event["outcome"]) == ("deploy.dns_edit", "requested")
    assert client.post(f"{RECORDS}/9", data=form).status_code == 404


MAIL = RetrievedRecord(
    provider_id="3", host="", type="MX", value="mx.example.net", ttl=3600, priority=10
)


def test_an_edit_keeps_what_it_is_not_told_to_change(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    """An MX record's edit opens holding its type, TTL and priority, and
    saves them as they are: an edit never turns it into an A record, or
    its TTL into the default."""
    registrar.records.append(MAIL)
    client = TestClient(app)
    edit = client.get(f"{RECORDS}/3/edit").text
    assert one(edit, "select[name=type] option[selected]").get("value") == "MX"
    assert one(edit, "input[name=ttl]").get("value") == "3600"
    assert one(edit, "input[name=priority]").get("value") == "10"
    form = {"host": "@", "type": "MX", "value": "mx2.example.net"}
    client.post(f"{RECORDS}/3", data=form | {"ttl": "3600", "priority": "10"})
    assert registrar.records[-1] == RetrievedRecord(
        "3", "", "MX", "mx2.example.net", 3600, 10
    )


def test_a_records_priority_is_listed(registrar: FakeRegistrar, app: FastAPI) -> None:
    """What the form sets, the list shows: an MX record's priority, none
    for a record without one (the adapter drops Porkbun's 0 for those)."""
    registrar.records.append(MAIL)
    rows = _rows(TestClient(app))
    assert [text(row["Priority"]) for row in rows] == ["-", "-", "10"]


def test_a_ttl_that_is_not_a_number_says_so(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    form = {"host": "api", "type": "A", "ttl": "soon", "priority": ""}
    response = TestClient(app).post(RECORDS, data=form)
    assert response.status_code == 422
    assert "TTL must be a whole number." in text(one(response.text, "form"))


def test_a_type_the_form_does_not_offer_is_kept(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    caa = RetrievedRecord("4", "", "CAA", '0 issue "letsencrypt.org"', 600)
    registrar.records.append(caa)
    edit = TestClient(app).get(f"{RECORDS}/4/edit").text
    assert one(edit, "select[name=type] option[selected]").get("value") == "CAA"


def test_a_new_record_takes_the_registrars_floor(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    client = TestClient(app)
    ttl = one(client.get(f"{RECORDS}/new").text, "input[name=ttl]")
    assert (ttl.get("value"), ttl.get("min")) == ("600", "600")
    client.post(RECORDS, data={"host": "api", "type": "A", "ttl": "", "priority": ""})
    assert (registrar.records[-1].ttl, registrar.records[-1].priority) == (600, None)


def test_a_record_other_than_a_needs_its_value(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    """The form comes back saying why, holding what was typed."""
    client = TestClient(app)
    audit = recording(client)
    response = client.post(RECORDS, data={"host": "mail", "type": "TXT"})
    assert response.status_code == 422
    assert "A TXT record needs its value." in text(one(response.text, "form"))
    assert one(response.text, "input[name=host]").get("value") == "mail"
    assert len(registrar.records) == 2
    assert audit.events[0]["outcome"] == "refused"


def test_a_delete_is_confirmed_then_audited(
    registrar: FakeRegistrar, app: FastAPI
) -> None:
    client = TestClient(app)
    audit = recording(client)
    confirm = client.get(f"{RECORDS}/2/confirm-delete").text
    assert text(one(confirm, "h2")) == "Delete A www.example.com?"
    assert one(confirm, "[hx-delete]").get("hx-delete") == f"{RECORDS}/2"
    assert client.delete(f"{RECORDS}/2").status_code == 204
    assert registrar.records == [APEX]
    (event,) = audit.events
    assert (event["event_type"], event["outcome"]) == (
        "deploy.dns_delete",
        "requested",
    )
    assert client.get(f"{RECORDS}/2/confirm-delete").status_code == 404


def test_without_keys_it_says_where_to_set_them(
    registrar: FakeRegistrar, store: FakeStore, app: FastAPI
) -> None:
    store.values.clear()
    html = page_html(TestClient(app), PAGE)
    card = one(html, "#deployments-dns")
    assert "Set the Porkbun keys" in text(card)
    assert one(card, "a").get("href") == f"{actions.PAGE}/settings"


def test_without_a_domain_it_says_so(
    registrar: FakeRegistrar, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    monkeypatch.setattr(settings, "BASE_DOMAIN", None)
    card = one(page_html(TestClient(app), PAGE), "#deployments-dns")
    assert "Set BASE_DOMAIN" in text(card)


def test_a_registrar_error_is_shown(
    registrar: FakeRegistrar, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    async def refused(domain: str) -> Any:
        raise RuntimeError("API ACCESS is off for example.com")

    monkeypatch.setattr(registrar, "list_dns_records", refused)
    card = one(page_html(TestClient(app), PAGE), "#deployments-dns")
    assert "API ACCESS is off for example.com" in text(card)
