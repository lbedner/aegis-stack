"""The Overseer Payment page: the account at a glance, every transaction,
subscription and dispute, a refund from a transaction's row, a cancel from
a subscription's, and a checkout link made against the live catalog.
Reads go through ``PaymentService`` on the request's session; the demo
seed stands in for a Stripe account."""

import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("app.services.payment", reason="no payment service in this stack")

from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.payment.constants import (  # noqa: E402
    SubscriptionStatus,
    TransactionStatus,
)
from app.services.payment.demo_seed import seed_fake_data  # noqa: E402
from app.services.payment.deps import get_payment_service  # noqa: E402
from app.services.payment.health import invalidate_payment_health_cache  # noqa: E402
from app.services.payment.providers.base import CatalogEntry  # noqa: E402
from app.services.payment.service import PaymentService  # noqa: E402
from app.services.system.models import ComponentStatus  # noqa: E402
from tests.web.dom import location, one, select, text, triggers  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

PAGE = "/overseer/services/payment"
PARTIALS = "/partials/overseer/payment"
PAYMENT = ComponentStatus(name="payment", message="Payment")


@pytest.fixture
def pay(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, async_client_with_db: TestClient
) -> TestClient:
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", None)
    # The provider probe is cached per process: another test's would stand in.
    invalidate_payment_health_cache()
    sign_in(app, monkeypatch, status_with(services=[PAYMENT]))
    return async_client_with_db


async def _seed(session: AsyncSession) -> dict[str, int]:
    provider = await PaymentService(session).get_or_create_provider()
    return await seed_fake_data(session, provider)


async def _catalog(service: object) -> list[CatalogEntry]:
    return [
        CatalogEntry(
            price_id="price_pro",
            product_name="Pro",
            amount=1000,
            currency="usd",
            interval="month",
            price_type="recurring",
        )
    ]


class _Recorder:
    """Stands in for ``PaymentService`` on the write routes: what each
    call was asked, and what it answers."""

    def __init__(self, answer: Any = True, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.answer, self.error = answer, error

    def _call(self, name: str, **kwargs: Any) -> Any:
        self.calls.append((name, kwargs))
        if self.error:
            raise self.error
        return self.answer

    async def refund_transaction(self, **kwargs: Any) -> Any:
        return self._call("refund", **kwargs)

    async def cancel_subscription(self, subscription_id: int) -> Any:
        return self._call("cancel", subscription_id=subscription_id)

    async def create_checkout(self, **kwargs: Any) -> Any:
        return self._call("checkout", **kwargs)


def _stub(app: FastAPI, recorder: _Recorder) -> _Recorder:
    app.dependency_overrides[get_payment_service] = lambda: recorder
    return recorder


def _get(client: TestClient, section: str = "", query: str = "") -> str:
    url = PAGE + (f"/{section}" if section else "") + (f"?{query}" if query else "")
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.text


def _figures(html: str) -> dict[str, str]:
    return {
        text(one(cell, "dt")): text(select(cell, "dd")[0])
        for cell in select(html, "#payment-figures > div")
    }


def _statuses(html: str, table: str, column: int) -> set[str]:
    """The status badges in one column of a list."""
    return {
        text(one(select(row, "td")[column], "[data-tone]"))
        for row in select(html, f"{table} tbody tr")
    }


def test_sections(pay: TestClient) -> None:
    assert [text(a) for a in select(_get(pay), "#overseer-subnav nav a")] == [
        "Overview",
        "Transactions",
        "Subscriptions",
        "Disputes",
        "Checkout",
    ]


async def test_the_overview_counts_the_account(
    pay: TestClient, async_db_session: AsyncSession
) -> None:
    made = await _seed(async_db_session)
    figures = _figures(_get(pay))
    assert figures["Transactions"] == f"{made['transactions']:,}"
    assert set(figures) == {
        "Transactions",
        "Revenue",
        "Active subscriptions",
        "Open disputes",
    }


def test_the_overview_charts_thirty_days_of_revenue(pay: TestClient) -> None:
    data = json.loads(text(one(_get(pay), "#chart-payment-revenue-data")))
    assert len(data["labels"]) == 30 and data["format"] == "money"


def test_an_unset_provider_names_the_missing_key(pay: TestClient) -> None:
    provider = text(one(_get(pay), "#payment-provider"))
    assert "Not configured" in provider and "STRIPE_SECRET_KEY" in provider


async def test_transactions_narrow_by_status(
    pay: TestClient, async_db_session: AsyncSession
) -> None:
    await _seed(async_db_session)
    html = _get(pay, "transactions", f"status={TransactionStatus.FAILED}")
    assert _statuses(html, "#payment-transactions", 2) == {"Failed"}


async def test_a_row_opens_its_transaction_in_the_drawer(
    pay: TestClient, async_db_session: AsyncSession
) -> None:
    await _seed(async_db_session)
    html = _get(pay, "transactions", f"status={TransactionStatus.SUCCEEDED}")
    href = one(select(html, "#payment-transactions tbody tr")[0], "a").get("href")
    assert "transaction=" in href and "status=succeeded" in href
    txn = href.split("transaction=")[1].split("&")[0]
    sync = one(_get(pay, "transactions", f"transaction={txn}"), "[data-drawer-sync]")
    assert sync.get("data-drawer-url") == f"{PARTIALS}/transactions/{txn}/drawer"


async def test_only_a_refundable_transaction_offers_a_refund(
    pay: TestClient, async_db_session: AsyncSession
) -> None:
    await _seed(async_db_session)
    offers: dict[str, bool] = {}
    for row in select(_get(pay, "transactions"), "#payment-transactions tbody tr"):
        txn = one(row, "a").get("href").split("transaction=")[1].split("&")[0]
        drawer = pay.get(f"{PARTIALS}/transactions/{txn}/drawer")
        assert drawer.status_code == 200, drawer.text
        offers[text(one(row, "[data-tone]"))] = bool(
            select(drawer.text, "form[data-refund]")
        )
    assert offers.get("Succeeded") is True and offers.get("Failed") is False


def test_a_partial_refund_goes_out_in_cents(app: FastAPI, pay: TestClient) -> None:
    service = _stub(app, _Recorder(answer=object()))
    response = pay.post(
        f"{PARTIALS}/transactions/7/refund",
        data={"amount": "12.50", "original": "4999", "reason": "duplicate"},
    )
    assert response.status_code == 200, response.text
    assert service.calls == [
        ("refund", {"transaction_id": 7, "amount": 1250, "reason": "duplicate"})
    ]
    assert "transaction=7" in location(response)


def test_the_whole_amount_is_a_full_refund(app: FastAPI, pay: TestClient) -> None:
    service = _stub(app, _Recorder(answer=object()))
    pay.post(
        f"{PARTIALS}/transactions/7/refund",
        data={"amount": "49.99", "original": "4999", "reason": "duplicate"},
    )
    assert service.calls[0][1]["amount"] is None


def test_a_bad_amount_is_refused(app: FastAPI, pay: TestClient) -> None:
    service = _stub(app, _Recorder())
    response = pay.post(
        f"{PARTIALS}/transactions/7/refund",
        data={"amount": "lots", "original": "4999", "reason": "duplicate"},
    )
    assert triggers(response)["toast"]["tone"] == "error" and not service.calls


def test_a_provider_refusal_is_the_toast(app: FastAPI, pay: TestClient) -> None:
    import stripe

    _stub(app, _Recorder(error=stripe.InvalidRequestError("Already refunded", None)))
    response = pay.post(
        f"{PARTIALS}/transactions/7/refund",
        data={"amount": "", "original": "4999", "reason": "duplicate"},
    )
    toast = triggers(response)["toast"]
    assert toast["tone"] == "error" and "Already refunded" in toast["text"]


async def test_subscriptions_show_who_is_billed(
    pay: TestClient, async_db_session: AsyncSession
) -> None:
    await _seed(async_db_session)
    html = _get(pay, "subscriptions", f"status={SubscriptionStatus.ACTIVE}")
    rows = select(html, "#payment-subscriptions tbody tr")
    assert rows and all(text(select(r, "td")[0]) != "-" for r in rows)
    assert _statuses(html, "#payment-subscriptions", 2) == {"Active"}


def test_cancelling_a_subscription_goes_to_the_service(
    app: FastAPI, pay: TestClient
) -> None:
    service = _stub(app, _Recorder(answer=object()))
    response = pay.post(f"{PARTIALS}/subscriptions/3/cancel")
    assert response.status_code == 200
    assert service.calls == [("cancel", {"subscription_id": 3})]


async def test_open_disputes_are_the_ones_to_answer(
    pay: TestClient, async_db_session: AsyncSession
) -> None:
    await _seed(async_db_session)
    html = _get(pay, "disputes", "status=open")
    found = _statuses(html, "#payment-disputes", 2)
    assert found and found <= {
        "Warning issued",
        "Needs response",
        "Under review",
    }


def test_checkout_waits_for_a_key(pay: TestClient) -> None:
    html = _get(pay, "checkout")
    assert "STRIPE_SECRET_KEY" in text(one(html, "#payment-checkout"))
    assert not select(html, "#payment-checkout form")


def test_checkout_offers_the_catalog(
    pay: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend import overseer_payment

    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(overseer_payment, "get_catalog", _catalog)
    options = select(_get(pay, "checkout"), "#payment-checkout select option")
    assert [o.get("value") for o in options] == ["price_pro"]
    assert "Pro" in text(options[0]) and "month" in text(options[0])


def test_a_checkout_link_comes_back(
    app: FastAPI, pay: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend.routes.partials import overseer_payment

    monkeypatch.setattr(overseer_payment, "get_catalog", _catalog)
    service = _stub(
        app,
        _Recorder(
            answer={"session_id": "cs_1", "checkout_url": "https://pay.example/cs_1"}
        ),
    )
    response = pay.post(
        f"{PARTIALS}/checkout", data={"price": "price_pro", "quantity": "1"}
    )
    assert response.status_code == 200, response.text
    assert service.calls[0][1]["mode"] == "subscription"
    assert one(response.text, "a[href='https://pay.example/cs_1']") is not None


def test_a_price_not_in_the_catalog_is_refused(
    app: FastAPI, pay: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend.routes.partials import overseer_payment

    monkeypatch.setattr(overseer_payment, "get_catalog", _catalog)
    service = _stub(app, _Recorder())
    response = pay.post(f"{PARTIALS}/checkout", data={"price": "price_gone"})
    assert triggers(response)["toast"]["tone"] == "error" and not service.calls
