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
