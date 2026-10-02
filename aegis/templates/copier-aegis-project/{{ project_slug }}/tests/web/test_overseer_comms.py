"""The Overseer Comms page: each channel (email, SMS, voice), whether it is
set up and exactly which settings are missing, and a test send where a
channel is ready. Comms keeps no history of its own, so there is nothing
else to show."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("app.services.comms", reason="no comms service in this stack")

from app.core.config import settings  # noqa: E402
from app.services.system.models import ComponentStatus  # noqa: E402
from tests.web.dom import one, select, text, triggers  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

PAGE = "/overseer/services/comms"
PARTIALS = "/partials/overseer/comms"
COMMS = ComponentStatus(name="comms", message="Comms")
KEYS = (
    "RESEND_API_KEY",
    "RESEND_FROM_EMAIL",
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "TWILIO_MESSAGING_SERVICE_SID",
)


@pytest.fixture
def comms(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key in KEYS:
        monkeypatch.setattr(settings, key, None)
    sign_in(app, monkeypatch, status_with(services=[COMMS]))
    return TestClient(app)


def _email_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "ops@example.com")


def _get(client: TestClient, section: str = "") -> str:
    response = client.get(PAGE + (f"/{section}" if section else ""))
    assert response.status_code == 200, response.text
    return response.text


def test_sections(comms: TestClient) -> None:
    assert [text(a) for a in select(_get(comms), "#overseer-subnav nav a")] == [
        "Overview",
        "Email",
        "SMS and voice",
    ]


def test_an_unset_channel_names_what_is_missing(comms: TestClient) -> None:
    email = one(_get(comms), "[data-channel='email']")
    assert "Not configured" in text(email)
    assert "RESEND_API_KEY" in text(email) and "RESEND_FROM_EMAIL" in text(email)


def test_a_set_channel_shows_where_it_sends_from(
    comms: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _email_ready(monkeypatch)
    email = one(_get(comms), "[data-channel='email']")
    assert "Configured" in text(email) and "ops@example.com" in text(email)
    assert "RESEND_API_KEY" not in text(email)


def test_every_channel_is_listed(comms: TestClient) -> None:
    channels = [c.get("data-channel") for c in select(_get(comms), "[data-channel]")]
    assert channels == ["email", "sms", "voice"]


def test_the_test_send_waits_for_a_configured_channel(
    comms: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        one(_get(comms, "email"), "#comms-test-email button[type=submit]").get(
            "disabled"
        )
        is not None
    )
    _email_ready(monkeypatch)
    assert (
        one(_get(comms, "email"), "#comms-test-email button[type=submit]").get(
            "disabled"
        )
        is None
    )


def test_a_test_email_goes_out(
    comms: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend.routes.partials import overseer_comms

    sent: list[tuple[str, str]] = []

    async def send(to: str, subject: str, text: str | None = None) -> object:
        sent.append((to, subject))
        return object()

    monkeypatch.setattr(overseer_comms, "send_email_simple", send)
    _email_ready(monkeypatch)
    response = comms.post(f"{PARTIALS}/test-email", data={"to": "me@example.com"})
    assert sent and sent[0][0] == "me@example.com"
    assert triggers(response)["toast"]["tone"] == "ok"


def test_a_provider_error_is_the_toast(
    comms: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend.routes.partials import overseer_comms
    from app.services.comms.email import EmailError

    async def fail(to: str, subject: str, text: str | None = None) -> object:
        raise EmailError("Domain not verified")

    monkeypatch.setattr(overseer_comms, "send_email_simple", fail)
    _email_ready(monkeypatch)
    toast = triggers(
        comms.post(f"{PARTIALS}/test-email", data={"to": "me@example.com"})
    )["toast"]
    assert toast["tone"] == "error" and "Domain not verified" in toast["text"]


def test_a_test_sms_goes_out(
    comms: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend.routes.partials import overseer_comms

    sent: list[str] = []

    async def send(to: str, body: str) -> object:
        sent.append(to)
        return object()

    monkeypatch.setattr(overseer_comms, "send_sms_simple", send)
    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setattr(settings, "TWILIO_PHONE_NUMBER", "+15550000000")
    response = comms.post(f"{PARTIALS}/test-sms", data={"to": "+15551234567"})
    assert sent == ["+15551234567"]
    assert triggers(response)["toast"]["tone"] == "ok"


def test_an_unset_channel_refuses_a_test_send(comms: TestClient) -> None:
    toast = triggers(comms.post(f"{PARTIALS}/test-sms", data={"to": "+15551234567"}))[
        "toast"
    ]
    assert toast["tone"] == "error" and "TWILIO_ACCOUNT_SID" in toast["text"]


def test_an_unset_channel_links_to_the_secrets_page(comms: TestClient) -> None:
    from app.components.web_frontend import overseer_secrets

    link = f"[data-channel='email'] a[href='{overseer_secrets.url()}']"
    assert one(_get(comms), link) is not None


def _domains(monkeypatch: pytest.MonkeyPatch, *domains: tuple[str, str]) -> None:
    from datetime import UTC, datetime

    from app.services.ops.adapters.resend import ResendAdapter
    from app.services.ops.types import DomainStatus

    async def list_domains(self: object) -> list[DomainStatus]:
        return [
            DomainStatus(name, status == "verified", status, datetime.now(UTC))
            for name, status in domains
        ]

    monkeypatch.setattr(ResendAdapter, "list_domains", list_domains)


def test_the_email_section_lists_resend_domains_with_a_check(
    comms: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _email_ready(monkeypatch)
    _domains(
        monkeypatch, ("mail.example.com", "verified"), ("new.example.com", "pending")
    )
    page = _get(comms, "email")
    domains = one(page, "#comms-domains")
    assert "mail.example.com" in text(domains) and "pending" in text(domains).lower()
    check = f'#comms-domains button[hx-post="{PARTIALS}/domains/new.example.com/check"]'
    assert one(page, check) is not None
    assert (
        one(page, f'#comms-domains button[hx-get="{PARTIALS}/domains/new"]') is not None
    )


def test_without_a_key_the_domains_card_says_what_to_set(comms: TestClient) -> None:
    domains = one(_get(comms, "email"), "#comms-domains")
    assert "RESEND_API_KEY" in text(domains)


def test_a_domain_resend_cannot_list_says_why(
    comms: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.ops.adapters.resend import ResendAdapter

    async def refuse(self: object) -> list[object]:
        raise RuntimeError("This API key is restricted to only send emails")

    _email_ready(monkeypatch)
    monkeypatch.setattr(ResendAdapter, "list_domains", refuse)
    assert "restricted" in text(one(_get(comms, "email"), "#comms-domains"))


def test_check_asks_resend_and_says_the_status(
    comms: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    from app.services.ops.adapters.resend import ResendAdapter
    from app.services.ops.types import DomainStatus

    async def check(self: object, domain: str) -> DomainStatus:
        return DomainStatus(domain, True, "verified", datetime.now(UTC))

    _email_ready(monkeypatch)
    monkeypatch.setattr(ResendAdapter, "check_domain", check)
    response = comms.post(f"{PARTIALS}/domains/new.example.com/check")
    assert response.status_code == 200
    assert "verified" in str(triggers(response)).lower()


def test_adding_a_domain_shows_the_dns_records_to_create(
    comms: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.ops.adapters.resend import ResendAdapter
    from app.services.ops.types import DnsRecord, DomainAddResult

    async def add(self: object, domain: str) -> DomainAddResult:
        record = DnsRecord(host="resend._domainkey", type="TXT", value="p=MIGf")
        return DomainAddResult(domain, [record], "dom_1")

    _email_ready(monkeypatch)
    monkeypatch.setattr(ResendAdapter, "add_domain", add)
    form = comms.get(f"{PARTIALS}/domains/new").text
    assert one(form, 'input[name="domain"]') is not None
    html = comms.post(f"{PARTIALS}/domains", data={"domain": "new.example.com"}).text
    rows = text(one(html, "#domain-records"))
    assert "resend._domainkey" in rows and "TXT" in rows and "p=MIGf" in rows
