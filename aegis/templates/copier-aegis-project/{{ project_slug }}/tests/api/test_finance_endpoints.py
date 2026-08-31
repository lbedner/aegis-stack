"""Tests for finance API endpoints.

Plain ``.py`` (only generated in finance-selected stacks). Exercises the
mounted router end to end via the async test client, mirroring
``test_blog_endpoints.py``.

The file renders identically for auth and no-auth stacks, so it drives the
API through ``authenticated_client`` (a passthrough without the auth
service) and seeds owner-scoped rows with ``acting_owner_user_id`` (``None``
without it). Using the plain client instead would 401 in every auth stack,
since the finance router resolves ``get_owner_user_id`` through
``get_current_active_user``; seeding with a hardcoded owner would then hide
those rows from the scoped reads.
"""

from datetime import date

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.service import FinanceService


@pytest.mark.asyncio
async def test_finance_health_returns_200_when_empty(
    authenticated_client: TestClient,
) -> None:
    """FIN-11 acceptance: GET /api/v1/finance/health -> 200 with zero counts."""
    response = authenticated_client.get("/api/v1/finance/health")
    assert response.status_code == 200
    body = response.json()
    assert body["accounts"] == 0
    assert body["connections"] == 0
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_finance_health_reflects_accounts(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    service = FinanceService(async_db_session)
    await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Chase Checking",
        account_type="checking",
        classification="asset",
    )
    await async_db_session.commit()

    response = authenticated_client.get("/api/v1/finance/health")
    assert response.status_code == 200
    assert response.json()["accounts"] == 1


@pytest.mark.asyncio
async def test_overview_composite_matches_granular_endpoints(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """One surface, one round trip: /overview returns every Overview
    section in the granular endpoints' own shapes, consistent with them."""
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Chase Checking",
        account_type="checking",
        classification="asset",
        current_balance=500_000,
    )
    today = date.today()
    await service.create_transaction(
        account_id=account.id,
        amount=-12_345,
        txn_date=today,
        owner_user_id=acting_owner_user_id,
        name="Groceries Run",
    )
    await async_db_session.commit()

    response = authenticated_client.get("/api/v1/finance/overview")
    assert response.status_code == 200
    body = response.json()
    for section in (
        "accounts",
        "net_worth",
        "cashflow",
        "top_payees",
        "projection",
        "recent_transactions",
        "uncategorized",
        "spending",
    ):
        assert section in body

    granular = authenticated_client.get("/api/v1/finance/accounts").json()
    assert body["accounts"]["total"] == granular["total"] == 1

    recent = body["recent_transactions"]
    assert recent["total"] == 1
    assert recent["items"][0]["name"] == "Groceries Run"
    # The uncategorized preview carries the FULL backlog count.
    assert body["uncategorized"]["total"] == 1
    assert body["cashflow"]["items"], "cashflow months render even when quiet"


@pytest.mark.asyncio
async def test_account_and_valuation_flow(
    authenticated_client: TestClient,
) -> None:
    """FIN-12 acceptance: create My House, value it twice, read both back,
    current_balance follows the latest valuation."""
    created = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "My House",
            "account_type": "property",
            "classification": "asset",
        },
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    v1 = authenticated_client.post(
        f"/api/v1/finance/accounts/{account_id}/valuations",
        json={"as_of_date": "2026-07-01", "value": 50_000_000},
    )
    assert v1.status_code == 201
    v2 = authenticated_client.post(
        f"/api/v1/finance/accounts/{account_id}/valuations",
        json={"as_of_date": "2026-07-04", "value": 50_500_000},
    )
    assert v2.status_code == 201

    series = authenticated_client.get(
        f"/api/v1/finance/accounts/{account_id}/valuations"
    )
    assert series.status_code == 200
    assert series.json()["total"] == 2

    accounts = authenticated_client.get("/api/v1/finance/accounts")
    house = next(a for a in accounts.json()["items"] if a["id"] == account_id)
    assert house["current_balance"] == 50_500_000


@pytest.mark.asyncio
async def test_bulk_valuation_ingest_from_a_pasted_series(
    authenticated_client: TestClient,
) -> None:
    """FW-03 acceptance: a decade of monthly estimates arrives as one paste,
    labelled with where it came from."""
    created = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "House Bedner",
            "account_type": "property",
            "classification": "asset",
        },
    )
    account_id = created.json()["id"]

    ingested = authenticated_client.post(
        f"/api/v1/finance/accounts/{account_id}/valuations/bulk",
        json={
            "text": "Date\tThis home\nAug 2026\t$711.2K\nJul 2026\t$708.5K\n",
            "source": "zillow",
            "is_estimate": True,
        },
    )

    assert ingested.status_code == 200
    assert ingested.json()["added"] == 2

    series = authenticated_client.get(
        f"/api/v1/finance/accounts/{account_id}/valuations"
    )
    assert series.json()["total"] == 2
    assert {v["source"] for v in series.json()["items"]} == {"zillow"}

    accounts = authenticated_client.get("/api/v1/finance/accounts")
    house = next(a for a in accounts.json()["items"] if a["id"] == account_id)
    assert house["current_balance"] == 71_120_000  # the newest row


@pytest.mark.asyncio
async def test_bulk_ingest_reports_an_unreadable_line(
    authenticated_client: TestClient,
) -> None:
    """Rejecting the paste beats importing 118 of 121 rows silently."""
    created = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "House",
            "account_type": "property",
            "classification": "asset",
        },
    )
    account_id = created.json()["id"]

    bad = authenticated_client.post(
        f"/api/v1/finance/accounts/{account_id}/valuations/bulk",
        json={"text": "Aug 2026\t$711.2K\nnonsense line\n", "source": "zillow"},
    )

    assert bad.status_code == 400
    assert "nonsense" in bad.json()["detail"]


@pytest.mark.asyncio
async def test_property_details_round_trip(
    authenticated_client: TestClient,
) -> None:
    """FW-02 acceptance: a property carries how it was bought and where its
    current number came from, and reads back on the account."""
    created = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "House Bedner",
            "account_type": "property",
            "classification": "asset",
        },
    )
    account_id = created.json()["id"]

    saved = authenticated_client.patch(
        f"/api/v1/finance/accounts/{account_id}/property",
        json={
            "purchase_price": 285_000_00,
            "purchase_date": "2016-08-01",
            "down_payment": 57_000_00,
            "valuation_source": "user",
            "valuation_as_of": "2026-08-01",
            "address_label": "House Bedner",
        },
    )

    assert saved.status_code == 200
    body = saved.json()
    assert body["property"]["purchase_price"] == 285_000_00
    assert body["property"]["valuation_source"] == "user"

    listed = authenticated_client.get("/api/v1/finance/accounts")
    house = next(a for a in listed.json()["items"] if a["id"] == account_id)
    assert house["property"]["down_payment"] == 57_000_00


@pytest.mark.asyncio
async def test_property_details_reject_a_bad_figure(
    authenticated_client: TestClient,
) -> None:
    """The model is the boundary: a rejected write is a 400, not a stored
    blob nobody validates again."""
    created = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "House",
            "account_type": "property",
            "classification": "asset",
        },
    )
    account_id = created.json()["id"]

    bad = authenticated_client.patch(
        f"/api/v1/finance/accounts/{account_id}/property",
        json={"purchase_price": 100, "down_payment": 101},
    )

    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_property_details_on_a_cash_account_are_refused(
    authenticated_client: TestClient,
) -> None:
    created = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "Checking",
            "account_type": "checking",
            "classification": "asset",
        },
    )
    account_id = created.json()["id"]

    refused = authenticated_client.patch(
        f"/api/v1/finance/accounts/{account_id}/property",
        json={"purchase_price": 1},
    )

    assert refused.status_code == 400


@pytest.mark.asyncio
async def test_valuation_repost_updates_in_place(
    authenticated_client: TestClient,
) -> None:
    created = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "House",
            "account_type": "property",
            "classification": "asset",
        },
    )
    account_id = created.json()["id"]
    for value in (100, 200):
        authenticated_client.post(
            f"/api/v1/finance/accounts/{account_id}/valuations",
            json={"as_of_date": "2026-07-01", "value": value},
        )
    series = authenticated_client.get(
        f"/api/v1/finance/accounts/{account_id}/valuations"
    )
    assert series.json()["total"] == 1  # upsert, not duplicate


@pytest.mark.asyncio
async def test_soft_delete_removes_from_listing(
    authenticated_client: TestClient,
) -> None:
    created = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "Temp",
            "account_type": "checking",
            "classification": "asset",
        },
    )
    account_id = created.json()["id"]
    deleted = authenticated_client.delete(f"/api/v1/finance/accounts/{account_id}")
    assert deleted.status_code == 204
    accounts = authenticated_client.get("/api/v1/finance/accounts")
    assert all(a["id"] != account_id for a in accounts.json()["items"])


@pytest.mark.asyncio
async def test_accounts_include_liability_detail_when_present(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """FIN-23: credit accounts with liability data carry it in the accounts
    listing; accounts without stay null (AMEX-graceful, no empty widget)."""
    from datetime import date

    from app.services.finance.models import FinanceLiabilityDetail

    service = FinanceService(async_db_session)
    card = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Chase Card",
        account_type="credit_card",
        classification="liability",
    )
    await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="AMEX Card",
        account_type="credit_card",
        classification="liability",
    )
    async_db_session.add(
        FinanceLiabilityDetail(
            owner_user_id=acting_owner_user_id,
            account_id=card.id,
            liability_type="credit",
            last_statement_balance=170877,
            minimum_payment_amount=3500,
            next_payment_due_date=date(2026, 7, 15),
            is_overdue=False,
        )
    )
    await async_db_session.commit()

    body = authenticated_client.get("/api/v1/finance/accounts").json()
    by_name = {a["name"]: a for a in body["items"]}
    liability = by_name["Chase Card"]["liability"]
    assert liability["minimum_payment_amount"] == 3500
    assert liability["next_payment_due_date"] == "2026-07-15"
    assert liability["last_statement_balance"] == 170877
    assert liability["is_overdue"] is False
    assert by_name["AMEX Card"]["liability"] is None


@pytest.mark.asyncio
async def test_unknown_account_returns_404(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.patch(
        "/api/v1/finance/accounts/999999", json={"name": "x"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_spending_summary_bad_month_returns_422(
    authenticated_client: TestClient,
) -> None:
    """A malformed or out-of-range ``month`` is a client error, not a 500."""
    for bad in ("not-a-month", "2026-13"):
        response = authenticated_client.get(
            "/api/v1/finance/spending/summary", params={"month": bad}
        )
        assert response.status_code == 422, bad


@pytest.mark.asyncio
async def test_net_worth_series_after_recompute(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """FIN-13 acceptance: House ($505k) + Mortgage ($300k) → net worth $205k."""
    from datetime import UTC, datetime, timedelta

    from app.services.finance.domains.ledger import networth

    today = datetime.now(UTC).date()
    # House with two valuations; Mortgage as a liability.
    house = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "My House",
            "account_type": "property",
            "classification": "asset",
        },
    ).json()
    for offset, value in ((5, 50_000_000), (2, 50_500_000)):
        authenticated_client.post(
            f"/api/v1/finance/accounts/{house['id']}/valuations",
            json={
                "as_of_date": (today - timedelta(days=offset)).isoformat(),
                "value": value,
            },
        )
    authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "Mortgage",
            "account_type": "loan",
            "classification": "liability",
            "current_balance": 30_000_000,
        },
    )

    # Materialize snapshots (the nightly job's work), then read the series.
    await networth.recompute_snapshots(
        async_db_session, owner_user_id=acting_owner_user_id
    )
    await async_db_session.commit()

    response = authenticated_client.get("/api/v1/finance/net-worth?days=90")
    assert response.status_code == 200
    series = response.json()
    assert series, "expected a net-worth series"
    assert series[-1]["net_worth_amount"] == 20_500_000


@pytest.mark.asyncio
async def test_all_trades_across_accounts(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """FIN-25: GET /trades returns investment activity across every account,
    newest first — the All Accounts register's investment lane."""
    from datetime import date

    service = FinanceService(async_db_session)
    roth = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Roth",
        account_type="brokerage",
        classification="asset",
    )
    ira = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="IRA",
        account_type="brokerage",
        classification="asset",
    )
    await service.upsert_trade(
        owner_user_id=acting_owner_user_id,
        account_id=roth.id,
        trade_type="buy",
        trade_date=date(2026, 6, 1),
        amount=-150_000,
    )
    await service.upsert_trade(
        owner_user_id=acting_owner_user_id,
        account_id=ira.id,
        trade_type="dividend",
        trade_date=date(2026, 6, 15),
        amount=1_250,
    )
    await async_db_session.commit()

    response = authenticated_client.get("/api/v1/finance/trades")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [t["type"] for t in body["items"]] == ["dividend", "buy"]
    assert {t["account_id"] for t in body["items"]} == {roth.id, ira.id}


@pytest.mark.asyncio
async def test_import_batch_report(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """FIN-14: GET /import/batches/{id} shows per-row outcomes."""
    from pathlib import Path

    from app.services.finance.adapters.importers import imports
    from app.services.finance.adapters.importers.ofx import parse_ofx

    fixture = (
        Path(__file__).parent.parent
        / "services"
        / "finance"
        / "fixtures"
        / "sample_chase.qfx"
    )
    data = fixture.read_bytes()

    account = await FinanceService(async_db_session).create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Chase Checking",
        account_type="checking",
        classification="asset",
    )
    result = await imports.ingest_transactions(
        async_db_session,
        owner_user_id=acting_owner_user_id,
        source_type="qfx",
        file_name="sample_chase.qfx",
        file_bytes=data,
        parsed=parse_ofx(data, source="qfx"),
        default_account_id=account.id,
    )
    await async_db_session.commit()

    response = authenticated_client.get(
        f"/api/v1/finance/import/batches/{result.batch_id}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rows_total"] == 6
    assert body["rows_inserted"] == 6
    assert len(body["rows"]) == 6
    assert all(r["parsed_status"] == "inserted" for r in body["rows"])


# ---------------------------------------------------------------------------
# FIN-17 — upload front door + read APIs
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402

_FIXTURES = Path(__file__).parent.parent / "services" / "finance" / "fixtures"


async def _checking_account(session: AsyncSession, owner_user_id: int | None) -> int:
    account = await FinanceService(session).create_manual_account(
        owner_user_id=owner_user_id,
        name="Chase Checking",
        account_type="checking",
        classification="asset",
    )
    await session.commit()
    return account.id


@pytest.mark.asyncio
async def test_upload_qif(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    account_id = await _checking_account(async_db_session, acting_owner_user_id)
    data = (_FIXTURES / "sample_quicken.qif").read_bytes()
    response = authenticated_client.post(
        "/api/v1/finance/import",
        files={"file": ("sample_quicken.qif", data, "text/plain")},
        params={"account_id": account_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rows_inserted"] == 8

    # transactions read API returns them, newest first, deduped rows excluded
    txns = authenticated_client.get(
        f"/api/v1/finance/transactions?account_id={account_id}"
    )
    assert txns.status_code == 200
    items = txns.json()["items"]
    assert len(items) == 8
    assert items[0]["date"] >= items[-1]["date"]


@pytest.mark.asyncio
async def test_upload_reupload_short_circuits(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    account_id = await _checking_account(async_db_session, acting_owner_user_id)
    data = (_FIXTURES / "sample_chase.qfx").read_bytes()
    files = {"file": ("sample_chase.qfx", data, "application/octet-stream")}
    first = authenticated_client.post(
        "/api/v1/finance/import", files=files, params={"account_id": account_id}
    )
    assert first.json()["rows_inserted"] == 6
    second = authenticated_client.post(
        "/api/v1/finance/import",
        files={"file": ("sample_chase.qfx", data, "application/octet-stream")},
        params={"account_id": account_id},
    )
    body = second.json()
    assert body["rows_inserted"] == 0
    assert body["rows_duplicate"] == body["rows_total"] == 6

    batches = authenticated_client.get("/api/v1/finance/import/batches")
    assert batches.status_code == 200
    assert len(batches.json()) >= 1


@pytest.mark.asyncio
async def test_upload_unknown_extension_415(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    account_id = await _checking_account(async_db_session, acting_owner_user_id)
    response = authenticated_client.post(
        "/api/v1/finance/import",
        files={"file": ("statement.pdf", b"%PDF-1.4", "application/pdf")},
        params={"account_id": account_id},
    )
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_upload_missing_account_404(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/v1/finance/import",
        files={"file": ("x.qif", b"!Type:Bank\n^\n", "text/plain")},
        params={"account_id": 999_999},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_oversized_413(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    account_id = await _checking_account(async_db_session, acting_owner_user_id)
    oversized = b"x" * (10 * 1024 * 1024 + 1)
    response = authenticated_client.post(
        "/api/v1/finance/import",
        files={"file": ("big.csv", oversized, "text/csv")},
        params={"account_id": account_id},
    )
    assert response.status_code == 413


def _await_job(client: TestClient, job_id: str, tries: int = 100) -> dict:
    """Follow a background job to its terminal state via the status endpoint.

    The SSE stream is the UI's path; tests use the JSON snapshot because
    TestClient's portal keeps the app loop alive between requests, so the
    job progresses while we ask.
    """
    import time

    for _ in range(tries):
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never finished")


@pytest.mark.asyncio
async def test_background_import_runs_as_a_job(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
    monkeypatch,
) -> None:
    """``background=true``: 202 + job id, terminal event carries the counts."""
    from contextlib import asynccontextmanager

    from app.components.backend.api.finance import imports as finance_imports_module

    @asynccontextmanager
    async def _session():
        yield async_db_session

    monkeypatch.setattr(finance_imports_module, "_job_session", _session)

    account_id = await _checking_account(async_db_session, acting_owner_user_id)
    data = (_FIXTURES / "sample_quicken.qif").read_bytes()
    response = authenticated_client.post(
        "/api/v1/finance/import",
        files={"file": ("sample_quicken.qif", data, "text/plain")},
        params={"account_id": account_id, "background": "true"},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]

    body = _await_job(authenticated_client, job_id)
    assert body["status"] == "done"
    assert body["result"]["rows_inserted"] == 8

    txns = authenticated_client.get(
        f"/api/v1/finance/transactions?account_id={account_id}"
    )
    assert len(txns.json()["items"]) == 8


@pytest.mark.asyncio
async def test_background_import_failure_lands_in_the_job_error(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
    monkeypatch,
) -> None:
    """A QIF without a target account fails INSIDE the job; the error text
    reaches the subscriber instead of dying in a log."""
    from contextlib import asynccontextmanager

    from app.components.backend.api.finance import imports as finance_imports_module

    @asynccontextmanager
    async def _session():
        yield async_db_session

    monkeypatch.setattr(finance_imports_module, "_job_session", _session)

    data = (_FIXTURES / "sample_quicken.qif").read_bytes()
    response = authenticated_client.post(
        "/api/v1/finance/import",
        files={"file": ("sample_quicken.qif", data, "text/plain")},
        params={"background": "true"},
    )

    assert response.status_code == 202
    body = _await_job(authenticated_client, response.json()["job_id"])
    assert body["status"] == "failed"
    assert "account_id" in body["error"]


@pytest.mark.asyncio
async def test_job_endpoints_404_for_unknown_ids(
    authenticated_client: TestClient,
) -> None:
    assert authenticated_client.get("/api/v1/jobs/nope").status_code == 404
    assert authenticated_client.get("/api/v1/jobs/nope/events").status_code == 404


@pytest.mark.asyncio
async def test_job_events_stream_ends_with_the_terminal_snapshot(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
    monkeypatch,
) -> None:
    """The SSE contract the LoadingOverlay consumes: status frames, then a
    terminal frame, then the stream closes itself."""
    from contextlib import asynccontextmanager
    import json as jsonlib

    from app.components.backend.api.finance import imports as finance_imports_module

    @asynccontextmanager
    async def _session():
        yield async_db_session

    monkeypatch.setattr(finance_imports_module, "_job_session", _session)

    account_id = await _checking_account(async_db_session, acting_owner_user_id)
    data = (_FIXTURES / "sample_quicken.qif").read_bytes()
    job_id = authenticated_client.post(
        "/api/v1/finance/import",
        files={"file": ("sample_quicken.qif", data, "text/plain")},
        params={"account_id": account_id, "background": "true"},
    ).json()["job_id"]
    _await_job(authenticated_client, job_id)  # let it finish first

    events = []
    with authenticated_client.stream(
        "GET", f"/api/v1/jobs/{job_id}/events"
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data:"):
                events.append(jsonlib.loads(line[len("data:") :]))

    assert events, "the stream must replay at least the terminal snapshot"
    assert events[-1]["status"] == "done"
    assert events[-1]["result"]["rows_inserted"] == 8


@pytest.mark.asyncio
async def test_manual_bill_lifecycle(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Declare a bill, see it in the list with curation fields, mute/unmute."""
    created = authenticated_client.post(
        "/api/v1/finance/recurring",
        json={
            "name": "Rent",
            "direction": "outflow",
            "frequency": "monthly",
            "expected_amount": 185000,
            "next_expected_date": "2026-08-01",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["source"] == "user"
    assert body["is_user_confirmed"] is True
    assert body["expected_amount"] == 185000

    listing = authenticated_client.get("/api/v1/finance/recurring").json()
    assert any(s["name"] == "Rent" for s in listing["items"])

    stream_id = body["id"]
    muted = authenticated_client.post(f"/api/v1/finance/recurring/{stream_id}/mute")
    assert muted.json()["is_muted"] is True
    unmuted = authenticated_client.post(f"/api/v1/finance/recurring/{stream_id}/unmute")
    assert unmuted.json()["is_muted"] is False


@pytest.mark.asyncio
async def test_recurring_list_includes_icon_and_staleness(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Only the list endpoint (not the single-row create/update responses)
    has the context to compute a favicon guess and a staleness read per
    stream."""
    from datetime import date, timedelta

    authenticated_client.post(
        "/api/v1/finance/recurring",
        json={
            "name": "Netflix",
            "direction": "outflow",
            "frequency": "monthly",
            "expected_amount": 1599,
            # RELATIVE to today, never a literal. Pinned to a date this
            # test passes until that date arrives and then fails forever
            # as "overdue != fresh", which reads as a staleness bug
            # rather than an expired fixture. The property being
            # asserted is "a date in the future" - so say that.
            "next_expected_date": (date.today() + timedelta(days=14)).isoformat(),
        },
    )

    listing = authenticated_client.get("/api/v1/finance/recurring").json()
    stream = next(s for s in listing["items"] if s["name"] == "Netflix")
    # The icon ships as inlined base64, fetched upstream at request time -
    # so the endpoint's contract here is that the field is PRESENT, not what
    # it holds (offline there is nothing to fetch and it comes back null).
    # Deriving "Netflix" -> netflix.com is covered directly, without a
    # network, in tests/services/test_merchant_icon.py.
    assert "icon_b64" in stream
    # Declared with a next_expected_date in the near future - not overdue,
    # not a zombie.
    assert stream["staleness"] == "fresh"
    assert "last_date" in stream


@pytest.mark.asyncio
async def test_recurring_edit_updates_declared_facts(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """PATCH edits the sent fields; omitted fields survive; unknown id 404s."""
    created = authenticated_client.post(
        "/api/v1/finance/recurring",
        json={
            "name": "Rent",
            "direction": "outflow",
            "frequency": "monthly",
            "expected_amount": 185000,
            "next_expected_date": "2026-08-01",
        },
    ).json()

    updated = authenticated_client.patch(
        f"/api/v1/finance/recurring/{created['id']}",
        json={"expected_amount": 190000, "next_expected_date": "2026-09-01"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["expected_amount"] == 190000
    assert body["next_expected_date"] == "2026-09-01"
    assert body["name"] == "Rent"
    assert body["frequency"] == "monthly"

    missing = authenticated_client.patch(
        "/api/v1/finance/recurring/999999", json={"name": "X"}
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_uncategorized_counts_the_source_apps_catchall_too(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """A NULL-only check reports a clean ledger on a Quicken import that
    carried a thousand rows in its own "Uncategorized" bucket. Both count."""
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    catchall = await service.get_or_create_category_from_hint("Uncategorized")
    groceries = await service.get_or_create_category_from_hint("Food:Groceries")
    for name, category in (
        ("no category at all", None),
        ("source said uncategorized", catchall),
        ("properly classified", groceries),
    ):
        txn = await service.create_transaction(
            owner_user_id=acting_owner_user_id,
            account_id=account.id,
            amount=-1000,
            txn_date=date.today(),
            name=name,
        )
        txn.category_id = category.id if category is not None else None
        async_db_session.add(txn)
    await async_db_session.commit()

    body = authenticated_client.get(
        "/api/v1/finance/uncategorized", params={"limit": 10}
    ).json()
    names = {item["name"] for item in body["items"]}
    assert body["total"] == 2
    assert "no category at all" in names
    assert "source said uncategorized" in names  # the whole point
    assert "properly classified" not in names


@pytest.mark.asyncio
async def test_uncategorized_q_filters_by_payee(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Same search /transactions already has - a case-insensitive
    substring match on ``name`` only."""
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    for name in ("Trader Joes", "Whole Foods"):
        await service.create_transaction(
            owner_user_id=acting_owner_user_id,
            account_id=account.id,
            amount=-1000,
            txn_date=date.today(),
            name=name,
        )
    await async_db_session.commit()

    body = authenticated_client.get(
        "/api/v1/finance/uncategorized", params={"limit": 10, "q": "trader"}
    ).json()
    names = {item["name"] for item in body["items"]}
    assert names == {"Trader Joes"}
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_uncategorized_from_filters_by_date(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Same trailing-window filter /transactions already has (``>=``,
    no upper bound) - the date range picker UncategorizedPanel shares
    with the Accounts register."""
    from datetime import date, timedelta

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    await service.create_transaction(
        owner_user_id=acting_owner_user_id,
        account_id=account.id,
        amount=-1000,
        txn_date=date.today() - timedelta(days=60),
        name="Old Charge",
    )
    await service.create_transaction(
        owner_user_id=acting_owner_user_id,
        account_id=account.id,
        amount=-1000,
        txn_date=date.today(),
        name="Recent Charge",
    )
    await async_db_session.commit()

    cutoff = (date.today() - timedelta(days=7)).isoformat()
    body = authenticated_client.get(
        "/api/v1/finance/uncategorized", params={"limit": 10, "from": cutoff}
    ).json()
    names = {item["name"] for item in body["items"]}
    assert names == {"Recent Charge"}
    assert body["total"] == 1


@pytest.mark.asyncio
async def test_uncategorized_account_ids_scopes_to_that_account(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Same account-scope filter Overview's charts use
    (``AccountFilter.params()``)."""
    from datetime import date

    service = FinanceService(async_db_session)
    checking = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    savings = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Savings",
        account_type="savings",
        classification="asset",
    )
    await service.create_transaction(
        owner_user_id=acting_owner_user_id,
        account_id=checking.id,
        amount=-1000,
        txn_date=date.today(),
        name="Checking Charge",
    )
    await service.create_transaction(
        owner_user_id=acting_owner_user_id,
        account_id=savings.id,
        amount=-1000,
        txn_date=date.today(),
        name="Savings Charge",
    )
    await async_db_session.commit()

    scoped = authenticated_client.get(
        "/api/v1/finance/uncategorized",
        params={"limit": 10, "account_ids": [checking.id]},
    ).json()
    assert {item["name"] for item in scoped["items"]} == {"Checking Charge"}
    assert scoped["total"] == 1


@pytest.mark.asyncio
async def test_uncategorized_empty_account_ids_means_nothing(
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """An explicit empty list means the frontend's "Remove all" state
    and must return nothing, not silently read as "no filter" - service
    level, same as the analogous ``account_transaction_totals`` guard
    (test_finance_service.py), since an empty list can't actually reach
    the GET endpoint over HTTP (it just drops out of the query string,
    which is why the frontend skips the request entirely in that state -
    see ``AccountFilter.params()``)."""
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    await service.create_transaction(
        owner_user_id=acting_owner_user_id,
        account_id=account.id,
        amount=-1000,
        txn_date=date.today(),
        name="Checking Charge",
    )
    await async_db_session.commit()

    result = await service.uncategorized_transactions(
        owner_user_id=acting_owner_user_id, account_ids=[]
    )
    assert result == ([], 0)


@pytest.mark.asyncio
async def test_categorize_transaction_sets_category(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    groceries = await service.get_or_create_category_from_hint("Food:Groceries")
    txn = await service.create_transaction(
        owner_user_id=acting_owner_user_id,
        account_id=account.id,
        amount=-1200,
        txn_date=date.today(),
        name="Trader Joes",
    )
    await async_db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/finance/transactions/{txn.id}/categorize",
        json={"category_id": groceries.id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["category_id"] == groceries.id
    assert body["category"] == groceries.name
    assert body["category_source"] == "user"

    missing = authenticated_client.post(
        "/api/v1/finance/transactions/999999/categorize",
        json={"category_id": groceries.id},
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_auto_categorize_previews_without_writing(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """The endpoint is a preview: it returns a suggestion but must not
    touch the transaction. Applying one is a separate categorize call."""
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    groceries = await service.get_or_create_category_from_hint("Food:Groceries")
    past = await service.create_transaction(
        owner_user_id=acting_owner_user_id,
        account_id=account.id,
        amount=-1000,
        txn_date=date(2026, 6, 1),
        name="Trader Joes",
    )
    await service.categorize_transaction(
        past.id, groceries.id, owner_user_id=acting_owner_user_id, source="user"
    )
    fresh = await service.create_transaction(
        owner_user_id=acting_owner_user_id,
        account_id=account.id,
        amount=-1500,
        txn_date=date.today(),
        name="Trader Joes",
    )
    await async_db_session.commit()

    response = authenticated_client.post("/api/v1/finance/transactions/auto-categorize")
    assert response.status_code == 200
    body = response.json()
    assert body["skipped"] == 0
    assert len(body["items"]) == 1
    suggestion = body["items"][0]
    assert suggestion["transaction_id"] == fresh.id
    assert suggestion["category_id"] == groceries.id
    assert suggestion["category_name"] == groceries.name

    await async_db_session.refresh(fresh)
    assert fresh.category_id is None
    assert fresh.category_source == "unset"


@pytest.mark.asyncio
async def test_top_payees_ranks_outflows_and_skips_transfers(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """The Overview payee card reads this. Transfers must be excluded or a
    card payment tops the list forever, and inflows are not "money taken"."""
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    rows = [
        ("Landlord", -180_000, False),
        ("Landlord", -20_000, False),
        ("Corner Store", -5_000, False),
        ("Card Payment", -900_000, True),  # transfer: biggest, must not rank
        ("Employer", 500_000, False),  # inflow: not an outflow
    ]
    for name, amount, transfer in rows:
        txn = await service.create_transaction(
            owner_user_id=acting_owner_user_id,
            account_id=account.id,
            amount=amount,
            txn_date=date.today(),
            name=name,
        )
        txn.is_transfer = transfer
        async_db_session.add(txn)
    await async_db_session.commit()

    body = authenticated_client.get(
        "/api/v1/finance/payees", params={"days": 30, "limit": 5}
    ).json()
    names = [item["payee"] for item in body["items"]]
    assert names[0] == "Landlord"  # biggest first
    assert body["items"][0]["amount"] == 200_000  # positive magnitude, summed
    assert body["items"][0]["transaction_count"] == 2
    assert "Card Payment" not in names  # transfer excluded
    assert "Employer" not in names  # inflow excluded


@pytest.mark.asyncio
async def test_cashflow_splits_income_from_spend_and_skips_transfers(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """The Overview bars read this. Transfers must not appear as BOTH
    income and spend - a card payment is money moved, and counting it
    twice inflates both bars for the same dollars."""
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    today = date.today()
    for amount, transfer in ((500_000, False), (-120_000, False), (-99_999, True)):
        txn = await service.create_transaction(
            owner_user_id=acting_owner_user_id,
            account_id=account.id,
            amount=amount,
            txn_date=today,
            name="row",
        )
        txn.is_transfer = transfer
        async_db_session.add(txn)
    await async_db_session.commit()

    body = authenticated_client.get(
        "/api/v1/finance/cashflow", params={"months": 6}
    ).json()
    assert body["total"] == 6  # quiet months still returned, at zero
    months = {m["month"]: m for m in body["items"]}
    current = months[f"{today.year:04d}-{today.month:02d}"]
    assert current["income"] == 500_000
    assert current["expense"] == 120_000  # positive magnitude, transfer excluded
    assert current["net"] == 380_000
    # The axis stays even: every bucket present and oldest first.
    keys = [m["month"] for m in body["items"]]
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_categories_listing_reports_usage_and_keeps_unused(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """The Categories tab reads this: signed totals (inflows kept, unlike
    the spending breakdown), and categories with no activity still listed
    so imported taxonomy is visible and prunable."""
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    groceries = await service.get_or_create_category_from_hint(
        "Food & Dining:Groceries"
    )
    salary = await service.get_or_create_category_from_hint("Personal Income:Salary")
    await service.get_or_create_category_from_hint("Pets:Grooming")  # never used
    for amount, category in ((-8540, groceries), (-1200, groceries), (500000, salary)):
        txn = await service.create_transaction(
            owner_user_id=acting_owner_user_id,
            account_id=account.id,
            amount=amount,
            txn_date=date.today(),
            name="row",
        )
        txn.category_id = category.id
        async_db_session.add(txn)
    await async_db_session.commit()

    body = authenticated_client.get("/api/v1/finance/categories").json()
    by_name = {item["name"]: item for item in body["items"]}
    assert by_name["Food & Dining:Groceries"]["transaction_count"] == 2
    assert by_name["Food & Dining:Groceries"]["total"] == -9740  # signed
    # Income is kept, not dropped as the spending breakdown does.
    assert by_name["Personal Income:Salary"]["total"] == 500000
    assert by_name["Personal Income:Salary"]["classification"] == "income"
    # An unused category is still listed, at zero.
    assert by_name["Pets:Grooming"]["transaction_count"] == 0
    assert by_name["Pets:Grooming"]["total"] == 0
    assert by_name["Pets:Grooming"]["last_used"] is None

    # A window that predates the rows zeroes the counts but keeps the rows.
    narrow = authenticated_client.get(
        "/api/v1/finance/categories", params={"days": 1}
    ).json()
    assert narrow["total"] == body["total"]


@pytest.mark.asyncio
async def test_recurring_projection_walks_balance_through_schedule(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Projection = today's cash balance, then scheduled income and
    commitment bills applied in date order with a running balance.
    Detected merchant rhythms (non-commitments) must not appear."""
    from datetime import date, timedelta

    from app.services.finance.models import FinanceRecurringStream

    service = FinanceService(async_db_session)
    await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
        current_balance=100_000,  # $1,000
    )
    await service.get_or_create_currency("usd")
    today = date.today()
    store_owner = 0 if acting_owner_user_id is None else acting_owner_user_id
    for junk_name, junk_direction in (
        ("Dollar General", "outflow"),
        ("Amazon Refunds", "inflow"),
    ):
        async_db_session.add(
            FinanceRecurringStream(
                owner_user_id=store_owner,
                name=junk_name,
                normalized_payee=junk_name.upper(),
                direction=junk_direction,
                frequency="semi_monthly",
                average_amount=914,
                amount_is_variable=True,
                currency="usd",
                status="mature",
                source="derived",
                next_expected_date=today + timedelta(days=5),
            )
        )
    await async_db_session.commit()

    for name, direction, amount, offset in (
        ("Paycheck", "inflow", 200_000, 1),
        ("Rent", "outflow", 50_000, 3),
    ):
        created = authenticated_client.post(
            "/api/v1/finance/recurring",
            json={
                "name": name,
                "direction": direction,
                "frequency": "monthly",
                "expected_amount": amount,
                "next_expected_date": (today + timedelta(days=offset)).isoformat(),
            },
        )
        assert created.status_code == 201

    body = authenticated_client.get(
        "/api/v1/finance/recurring/projection", params={"days": 40}
    ).json()
    assert body["start_balance"] == 100_000
    # Account comes off the stream; category is derived from the stream's
    # member transactions (the stream table's own category_id is a
    # provider field the local detector never fills).
    assert all("account" in p and "category" in p for p in body["points"])
    # 40 days hold two monthly cycles of each stream.
    assert body["total"] == 4
    assert body["end_balance"] == 100_000 + 2 * 200_000 - 2 * 50_000
    assert body["upcoming_total"] == body["end_balance"] - body["start_balance"]
    assert body["points"][0]["name"] == "Paycheck"
    assert body["points"][0]["balance"] == 300_000
    dates = [p["date"] for p in body["points"]]
    assert dates == sorted(dates)
    # Variable detected rhythms project in neither direction.
    names = {p["name"] for p in body["points"]}
    assert "Dollar General" not in names
    assert "Amazon Refunds" not in names


@pytest.mark.asyncio
async def test_recurring_delete_drops_from_listing_and_mutes_detected(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """DELETE soft-deletes; a derived stream is also muted so the detector
    resurrecting it cannot bring it back loud. Unknown id 404s."""
    from sqlmodel import select

    from app.services.finance.models import FinanceRecurringStream
    from app.services.finance.service import FinanceService

    created = authenticated_client.post(
        "/api/v1/finance/recurring",
        json={
            "name": "Rent",
            "direction": "outflow",
            "frequency": "monthly",
            "expected_amount": 185000,
            "next_expected_date": "2026-08-01",
        },
    ).json()
    assert (
        authenticated_client.delete(
            f"/api/v1/finance/recurring/{created['id']}"
        ).status_code
        == 204
    )
    listing = authenticated_client.get("/api/v1/finance/recurring").json()
    assert not any(s["id"] == created["id"] for s in listing["items"])

    await FinanceService(async_db_session).get_or_create_currency("usd")
    store_owner = 0 if acting_owner_user_id is None else acting_owner_user_id
    derived = FinanceRecurringStream(
        owner_user_id=store_owner,
        name="Dollar General",
        normalized_payee="DOLLAR GENERAL",
        direction="outflow",
        frequency="semi_monthly",
        average_amount=914,
        amount_is_variable=True,
        currency="usd",
        status="mature",
        source="derived",
    )
    async_db_session.add(derived)
    await async_db_session.commit()
    derived_id = derived.id

    assert (
        authenticated_client.delete(
            f"/api/v1/finance/recurring/{derived_id}"
        ).status_code
        == 204
    )
    async_db_session.expire_all()
    row = (
        await async_db_session.exec(
            select(FinanceRecurringStream).where(
                FinanceRecurringStream.id == derived_id
            )
        )
    ).first()
    assert row is not None
    assert row.deleted_at is not None
    assert row.is_muted is True

    assert (
        authenticated_client.delete("/api/v1/finance/recurring/999999").status_code
        == 404
    )


@pytest.mark.asyncio
async def test_recurring_edit_detected_stream_pins_amount_keeps_payee_key(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Editing a detected stream pins the amount fixed, but renaming must
    not re-key normalized_payee - that key is how the detector re-finds
    the stream, and changing it would spawn a duplicate next pass."""
    from sqlmodel import select

    from app.services.finance.models import FinanceRecurringStream
    from app.services.finance.service import FinanceService

    await FinanceService(async_db_session).get_or_create_currency("usd")
    store_owner = 0 if acting_owner_user_id is None else acting_owner_user_id
    stream = FinanceRecurringStream(
        owner_user_id=store_owner,
        name="Dollar General",
        normalized_payee="DOLLAR GENERAL",
        direction="outflow",
        frequency="semi_monthly",
        average_amount=914,
        amount_is_variable=True,
        currency="usd",
        status="mature",
        source="derived",
    )
    async_db_session.add(stream)
    await async_db_session.commit()

    response = authenticated_client.patch(
        f"/api/v1/finance/recurring/{stream.id}",
        json={"name": "DG store card", "expected_amount": 1000},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "DG store card"
    assert body["expected_amount"] == 1000
    assert body["amount_is_variable"] is False

    stream_id = stream.id
    async_db_session.expire_all()
    row = (
        await async_db_session.exec(
            select(FinanceRecurringStream).where(FinanceRecurringStream.id == stream_id)
        )
    ).first()
    assert row is not None and row.normalized_payee == "DOLLAR GENERAL"


@pytest.mark.asyncio
async def test_recurring_confirm_promotes_a_detected_stream(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    from app.services.finance.models import FinanceRecurringStream
    from app.services.finance.service import FinanceService

    await FinanceService(async_db_session).get_or_create_currency("usd")
    store_owner = 0 if acting_owner_user_id is None else acting_owner_user_id
    stream = FinanceRecurringStream(
        owner_user_id=store_owner,
        name="Dollar General",
        normalized_payee="DOLLAR GENERAL",
        direction="outflow",
        frequency="semi_monthly",
        average_amount=914,
        amount_is_variable=True,
        currency="usd",
        status="mature",
        source="derived",
    )
    async_db_session.add(stream)
    await async_db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/finance/recurring/{stream.id}/confirm"
    )
    assert response.status_code == 200
    assert response.json()["is_user_confirmed"] is True


@pytest.mark.asyncio
async def test_monthly_rollup_counts_commitments_only(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Detected merchant rhythms (variable, unconfirmed) must not inflate
    the "per month in recurring bills" figure; declared bills count."""
    from datetime import date

    from app.services.finance.models import FinanceRecurringStream
    from app.services.finance.service import FinanceService

    service = FinanceService(async_db_session)
    await service.create_recurring_stream(
        owner_user_id=acting_owner_user_id,
        name="Rent",
        direction="outflow",
        frequency="monthly",
        expected_amount=185_000,
        next_expected_date=date(2026, 8, 1),
    )
    store_owner = 0 if acting_owner_user_id is None else acting_owner_user_id
    async_db_session.add(
        FinanceRecurringStream(
            owner_user_id=store_owner,
            name="Dollar General",
            normalized_payee="DOLLAR GENERAL",
            direction="outflow",
            frequency="semi_monthly",
            average_amount=914,
            amount_is_variable=True,
            currency="usd",
            status="mature",
            source="derived",
        )
    )
    await async_db_session.commit()

    body = authenticated_client.get("/api/v1/finance/recurring").json()
    assert body["total"] == 2  # both listed and curatable
    assert body["monthly_cost"] == 185_000  # only the commitment counts


# -- Budget ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_line_round_trip_and_summary(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    groceries = await service.get_or_create_category_from_hint("Food:Groceries")
    await service.create_transaction(
        owner_user_id=acting_owner_user_id,
        account_id=account.id,
        amount=-6_000,
        txn_date=date.today().replace(day=1),
        category_id=groceries.id,
    )
    await async_db_session.commit()

    created = authenticated_client.post(
        "/api/v1/finance/budget/lines",
        json={"category_id": groceries.id, "allocated_amount": 5_000},
    )
    assert created.status_code == 200
    line = created.json()
    assert line["category_id"] == groceries.id
    assert line["allocated_amount"] == 5_000
    assert line["spent_amount"] == 6_000
    assert line["status"] == "critical"

    summary = authenticated_client.get("/api/v1/finance/budget/summary").json()
    flexible = next(b for b in summary["buckets"] if b["name"] == "flexible")
    assert any(row["id"] == line["id"] for row in flexible["lines"])

    deleted = authenticated_client.delete(f"/api/v1/finance/budget/lines/{line['id']}")
    assert deleted.status_code == 204
    missing = authenticated_client.delete(f"/api/v1/finance/budget/lines/{line['id']}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_budget_line_rejects_both_category_and_payee(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
) -> None:
    groceries = await FinanceService(async_db_session).get_or_create_category_from_hint(
        "Food:Groceries"
    )
    await async_db_session.commit()

    response = authenticated_client.post(
        "/api/v1/finance/budget/lines",
        json={
            "category_id": groceries.id,
            "payee_key": "STARBUCKS",
            "allocated_amount": 100,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_budget_goal_parses_natural_language(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    from datetime import date

    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    for day in (1, 8, 15, 22):
        await service.create_transaction(
            owner_user_id=acting_owner_user_id,
            account_id=account.id,
            amount=-600,
            txn_date=date(2026, 7, day),
            name="Starbucks",
        )
    await async_db_session.commit()

    response = authenticated_client.post(
        "/api/v1/finance/budget/goal",
        json={"text": "I wanna cut back on Starbucks"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["target_type"] == "payee"
    assert body["payee_key"] == "STARBUCKS"
    assert body["suggested_limit"] == round(body["baseline_monthly"] * 0.5)


@pytest.mark.asyncio
async def test_budget_goal_no_match(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/v1/finance/budget/goal",
        json={"text": "gibberish with no history behind it"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False


@pytest.mark.asyncio
async def test_payee_can_be_edited_directly(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """PATCH /merchants/{id} edits a payee without re-filing anything.

    Replaces the only previous route to a payee's website, which ran
    through /payee-groups/assign and moved transactions as a side effect.
    """
    created = authenticated_client.post(
        "/api/v1/finance/merchants", json={"name": "Citizens"}
    ).json()

    patched = authenticated_client.patch(
        f"/api/v1/finance/merchants/{created['id']}",
        json={"website_url": "citizensbank.com", "name": "Citizens Bank"},
    )

    assert patched.status_code == 200
    body = patched.json()
    assert body["website_url"] == "citizensbank.com"
    assert body["name"] == "Citizens Bank"

    listed = authenticated_client.get("/api/v1/finance/merchants").json()
    row = next(m for m in listed["items"] if m["id"] == created["id"])
    assert row["website_url"] == "citizensbank.com"
    # Usage travels with the directory so the tab can show weight.
    assert "transaction_count" in row


@pytest.mark.asyncio
async def test_patching_an_unknown_payee_404s(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.patch(
        "/api/v1/finance/merchants/999999", json={"name": "Nope"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_payees_can_be_merged(
    authenticated_client: TestClient,
) -> None:
    """Two payees for one merchant is the normal end state of hand-naming;
    renaming does not join them, so merge has to."""
    keep = authenticated_client.post(
        "/api/v1/finance/merchants", json={"name": "Shop Rite"}
    ).json()
    drop = authenticated_client.post(
        "/api/v1/finance/merchants", json={"name": "ShopRite"}
    ).json()

    merged = authenticated_client.post(
        f"/api/v1/finance/merchants/{keep['id']}/merge",
        json={"source_ids": [drop["id"]]},
    )

    assert merged.status_code == 200
    listed = authenticated_client.get("/api/v1/finance/merchants").json()
    ids = {m["id"] for m in listed["items"]}
    assert keep["id"] in ids
    assert drop["id"] not in ids


class TestTags:
    """Tags as the user-defined flag: attach in bulk, see them on the
    register payload, click one to filter, detach one row at a time."""

    async def _two_transactions(
        self, session: AsyncSession, owner: int | None
    ) -> list[int]:
        from datetime import date as date_cls

        svc = FinanceService(session)
        account = await svc.create_manual_account(
            owner_user_id=owner,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        ids = []
        for day in (1, 2):
            txn = await svc.create_transaction(
                account_id=account.id,
                amount=-1_000 * day,
                txn_date=date_cls(2026, 8, day),
                owner_user_id=owner,
                name=f"Purchase {day}",
            )
            ids.append(txn.id)
        await session.commit()
        return ids

    @pytest.mark.asyncio
    async def test_tagging_then_reading_back_the_directory(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        ids = await self._two_transactions(async_db_session, acting_owner_user_id)

        tagged = authenticated_client.post(
            "/api/v1/finance/transactions/tags",
            json={"transaction_ids": ids, "name": "Flagged"},
        )

        assert tagged.status_code == 200
        tag = tagged.json()
        assert tag["name"] == "Flagged"

        listed = authenticated_client.get("/api/v1/finance/tags").json()
        assert [(t["name"], t["transaction_count"]) for t in listed] == [("Flagged", 2)]

    @pytest.mark.asyncio
    async def test_the_register_carries_tags_and_filters_by_one(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        ids = await self._two_transactions(async_db_session, acting_owner_user_id)
        tag = authenticated_client.post(
            "/api/v1/finance/transactions/tags",
            json={"transaction_ids": ids[:1], "name": "Flagged"},
        ).json()

        rows = authenticated_client.get("/api/v1/finance/transactions").json()
        by_id = {r["id"]: r for r in rows["items"]}
        assert [t["name"] for t in by_id[ids[0]]["tags"]] == ["Flagged"]
        assert by_id[ids[1]]["tags"] == []

        filtered = authenticated_client.get(
            "/api/v1/finance/transactions", params={"tag_id": tag["id"]}
        ).json()
        assert filtered["total"] == 1
        assert filtered["items"][0]["id"] == ids[0]

    @pytest.mark.asyncio
    async def test_untagging_one_row_leaves_the_rest(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        ids = await self._two_transactions(async_db_session, acting_owner_user_id)
        tag = authenticated_client.post(
            "/api/v1/finance/transactions/tags",
            json={"transaction_ids": ids, "name": "Flagged"},
        ).json()

        removed = authenticated_client.delete(
            f"/api/v1/finance/transactions/{ids[0]}/tags/{tag['id']}"
        )

        assert removed.status_code == 200
        assert removed.json() == {"removed": 1}
        listed = authenticated_client.get("/api/v1/finance/tags").json()
        assert [(t["name"], t["transaction_count"]) for t in listed] == [("Flagged", 1)]


class TestDeleteTransactions:
    """POST /transactions/delete - bulk soft delete from the register."""

    @pytest.mark.asyncio
    async def test_deleting_removes_rows_from_the_register(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        from datetime import date as date_cls

        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        ids = []
        for day in (1, 2, 3):
            txn = await svc.create_transaction(
                account_id=account.id,
                amount=-1_000 * day,
                txn_date=date_cls(2026, 8, day),
                owner_user_id=acting_owner_user_id,
                name=f"Purchase {day}",
            )
            ids.append(txn.id)
        await async_db_session.commit()

        response = authenticated_client.post(
            "/api/v1/finance/transactions/delete",
            json={"transaction_ids": ids[:2]},
        )

        assert response.status_code == 200
        assert response.json() == {"deleted": 2}
        listed = authenticated_client.get("/api/v1/finance/transactions").json()
        assert listed["total"] == 1
        assert listed["items"][0]["id"] == ids[2]

    @pytest.mark.asyncio
    async def test_deleting_nothing_real_reports_zero(
        self,
        authenticated_client: TestClient,
    ) -> None:
        response = authenticated_client.post(
            "/api/v1/finance/transactions/delete",
            json={"transaction_ids": [999999]},
        )
        assert response.status_code == 200
        assert response.json() == {"deleted": 0}


@pytest.mark.asyncio
async def test_import_preview_is_a_pure_read_then_commit_matches(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """FIN-33: POST /import/preview classifies without writing; the commit
    then reports the same counts."""
    account_id = await _checking_account(async_db_session, acting_owner_user_id)
    data = (_FIXTURES / "sample_quicken.qif").read_bytes()
    files = {"file": ("sample_quicken.qif", data, "text/plain")}
    preview = authenticated_client.post(
        "/api/v1/finance/import/preview",
        files=files,
        params={"account_id": account_id},
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["identical_batch_id"] is None
    assert body["rows_inserted"] == 8
    assert body["rows_updated"] == body["rows_error"] == 0
    assert body["inserts_by_account"] == {"Chase Checking": 8}
    assert body["insert_date_start"] == "2026-07-01"
    assert body["insert_date_end"] == "2026-07-08"

    # Nothing was written: no batch exists until the real import runs.
    assert authenticated_client.get("/api/v1/finance/import/batches").json() == []

    committed = authenticated_client.post(
        "/api/v1/finance/import",
        files={"file": ("sample_quicken.qif", data, "text/plain")},
        params={"account_id": account_id},
    )
    assert committed.status_code == 200
    assert committed.json()["rows_inserted"] == body["rows_inserted"]

    # An identical-file preview now short-circuits instead of re-planning.
    again = authenticated_client.post(
        "/api/v1/finance/import/preview",
        files={"file": ("sample_quicken.qif", data, "text/plain")},
        params={"account_id": account_id},
    )
    assert again.status_code == 200
    assert again.json()["identical_batch_id"] is not None


@pytest.mark.asyncio
async def test_preview_splits_out_rows_for_removed_accounts(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """Deleting an account is a standing decision: a re-import preview
    reports its rows as ignored (named, counted) instead of offering to
    recreate the account."""
    service = FinanceService(async_db_session)
    amex = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="AMEX CARD",
        account_type="credit_card",
        classification="liability",
    )
    await service.soft_delete_account(amex.id, owner_user_id=acting_owner_user_id)

    from app.services.finance.models import FinanceImportProfile
    from app.services.finance.seeds.seed import CSV_IMPORT_PROFILES, DEFAULT_CURRENCIES

    for currency in DEFAULT_CURRENCIES:
        await service.get_or_create_currency(currency["code"])
    for profile in CSV_IMPORT_PROFILES:
        async_db_session.add(FinanceImportProfile(is_system=True, **profile))
    await async_db_session.commit()

    data = (_FIXTURES / "sample_quicken_all.csv").read_bytes()
    preview = authenticated_client.post(
        "/api/v1/finance/import/preview",
        files={"file": ("sample_quicken_all.csv", data, "text/csv")},
    )

    assert preview.status_code == 200
    body = preview.json()
    # The three AMEX CARD rows are ignored - not skipped, not landing anywhere.
    assert body["rows_ignored"] == 3
    assert body["rows_skipped"] == 0
    assert body["removed_accounts"] == ["AMEX CARD"]
    assert body["new_accounts"] == ["CHECKING"]
    assert "AMEX CARD" not in body["inserts_by_account"]
    assert body["rows_inserted"] == 2


@pytest.mark.asyncio
async def test_creating_a_category_returns_it_for_immediate_use(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
) -> None:
    """There was no way to make a category anywhere in the UI, so a
    miscategorized batch could only be fixed by hand into a taxonomy that
    did not have the right row in it."""
    response = authenticated_client.post(
        "/api/v1/finance/categories", json={"name": "Kids:Activities"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Kids:Activities"
    assert body["id"]

    options = authenticated_client.get("/api/v1/finance/categories/options").json()
    assert "Kids:Activities" in {c["name"] for c in options["items"]}


@pytest.mark.asyncio
async def test_a_near_duplicate_returns_the_same_category(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
) -> None:
    """The reason inline creation was withheld: "inventing categories
    inline is how a category list turns into 400 near-duplicates".

    It resolves by SLUG, so spacing and case collapse onto the row that
    already exists. Get-or-create, not create.
    """
    first = authenticated_client.post(
        "/api/v1/finance/categories", json={"name": "Kids:Activities"}
    ).json()
    again = authenticated_client.post(
        "/api/v1/finance/categories", json={"name": "kids:  ACTIVITIES "}
    ).json()

    assert again["id"] == first["id"]
    options = authenticated_client.get("/api/v1/finance/categories/options").json()
    kids = [c for c in options["items"] if c["name"].lower().startswith("kids")]
    assert len(kids) == 1


@pytest.mark.asyncio
async def test_payee_grade_depth_is_folded_back_to_two_levels(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
) -> None:
    """The other half of the same guard, and the house convention every
    existing category follows: a third segment is a merchant, not a
    category."""
    body = authenticated_client.post(
        "/api/v1/finance/categories", json={"name": "Kids:Activities:Soccer Club"}
    ).json()

    assert body["name"] == "Kids:Activities"


@pytest.mark.asyncio
async def test_an_empty_name_is_refused(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
) -> None:
    response = authenticated_client.post(
        "/api/v1/finance/categories", json={"name": "   "}
    )

    assert response.status_code == 422


async def _brokerage_account(session: AsyncSession, owner_user_id: int | None) -> int:
    account = await FinanceService(session).create_manual_account(
        owner_user_id=owner_user_id,
        name="HSA Investments",
        account_type="brokerage",
        classification="asset",
    )
    await session.commit()
    return account.id


class TestImportInvestmentsPreview:
    """Parse-only look at a ledger, before any account exists or is chosen."""

    @pytest.mark.asyncio
    async def test_preview_reports_positions_without_writing(
        self, authenticated_client: TestClient
    ) -> None:
        data = (_FIXTURES / "optum_hsa_sample.tsv").read_bytes()
        response = authenticated_client.post(
            "/api/v1/finance/import-investments/preview",
            files={"file": ("optum_hsa_sample.tsv", data, "text/tab-separated-values")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["activities_parsed"] == 7
        assert body["first_date"] == "2022-02-17"
        assert body["last_date"] == "2024-12-13"
        by_name = {p["name"]: p for p in body["positions"]}
        assert by_name["Schwab Small Cap Index"]["shares"] == 55.85
        # Value rides each position, at the security's LAST price seen in
        # the ledger: 55.85 shares x $38.00 (the 12/13/2024 dividend row).
        assert by_name["Schwab Small Cap Index"]["value"] == 212_230
        # Exchanged-away share class replays to zero and stays visible -
        # the preview shows the replay, not a prettied subset of it.
        assert by_name["Vanguard Total Int Stk Idx Adm"]["shares"] == 0.0
        assert by_name["Vanguard Total Int Stk Idx Adm"]["value"] == 0
        # 14.000 shares x $115.00 exchange-in price.
        assert by_name["Vanguard Total Intl Stk Idx I"]["value"] == 161_000
        assert body["total_value"] == 212_230 + 161_000

        # Nothing was written: no accounts sprang into being.
        accounts = authenticated_client.get("/api/v1/finance/accounts")
        assert accounts.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_unrecognized_activity_type_is_422(
        self, authenticated_client: TestClient
    ) -> None:
        bogus = (
            "Settled Transactions 01/01/2020 to 08/10/2026\n"
            "Transaction Date\tDescription\tType\tUnits\tPrice\tTotal Amount\n"
            "01/01/2024\tSome Fund\tMYSTERY MEAT\t1\t$1.00\t$1.00\n"
        )
        response = authenticated_client.post(
            "/api/v1/finance/import-investments/preview",
            files={"file": ("bogus.tsv", bogus.encode(), "text/tab-separated-values")},
        )
        assert response.status_code == 422


class TestImportInvestments:
    """The Import menu's investment lane: /import-investments commits into an
    existing account, or creates one - the same courtesy OFX ingest extends."""

    @pytest.mark.asyncio
    async def test_imports_into_an_existing_account(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        account_id = await _brokerage_account(async_db_session, acting_owner_user_id)
        data = (_FIXTURES / "optum_hsa_sample.tsv").read_bytes()
        response = authenticated_client.post(
            "/api/v1/finance/import-investments",
            files={"file": ("optum_hsa_sample.tsv", data, "text/tab-separated-values")},
            params={"account_id": account_id},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["activities_parsed"] == 7
        assert body["trades_inserted"] == 7
        assert body["securities_created"] == 3
        assert body["account_id"] == account_id
        assert body["account_created"] is False

        holdings = authenticated_client.get(
            f"/api/v1/finance/accounts/{account_id}/holdings"
        )
        assert holdings.status_code == 200
        tickers = {h["ticker"] for h in holdings.json()["items"]}
        # Admiral share class fully exchanged away -> not a current holding.
        assert "Vanguard Total Int Stk Idx Adm" not in tickers

    @pytest.mark.asyncio
    async def test_creates_the_account_when_given_a_name(
        self, authenticated_client: TestClient
    ) -> None:
        data = (_FIXTURES / "optum_hsa_sample.tsv").read_bytes()
        response = authenticated_client.post(
            "/api/v1/finance/import-investments",
            files={"file": ("optum_hsa_sample.tsv", data, "text/tab-separated-values")},
            params={"account_name": "HSA Investments"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["account_created"] is True
        assert body["account_name"] == "HSA Investments"
        assert body["trades_inserted"] == 7

        accounts = authenticated_client.get("/api/v1/finance/accounts").json()
        account = next(a for a in accounts["items"] if a["id"] == body["account_id"])
        assert account["account_type"] == "brokerage"
        assert account["classification"] == "asset"

    @pytest.mark.asyncio
    async def test_no_target_at_all_is_400(
        self, authenticated_client: TestClient
    ) -> None:
        data = (_FIXTURES / "optum_hsa_sample.tsv").read_bytes()
        response = authenticated_client.post(
            "/api/v1/finance/import-investments",
            files={"file": ("optum_hsa_sample.tsv", data, "text/tab-separated-values")},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_account_is_404(
        self, authenticated_client: TestClient
    ) -> None:
        data = (_FIXTURES / "optum_hsa_sample.tsv").read_bytes()
        response = authenticated_client.post(
            "/api/v1/finance/import-investments",
            files={"file": ("optum_hsa_sample.tsv", data, "text/tab-separated-values")},
            params={"account_id": 999999},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_unknown_profile_is_400(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        account_id = await _brokerage_account(async_db_session, acting_owner_user_id)
        data = (_FIXTURES / "optum_hsa_sample.tsv").read_bytes()
        response = authenticated_client.post(
            "/api/v1/finance/import-investments",
            files={"file": ("optum_hsa_sample.tsv", data, "text/tab-separated-values")},
            params={"account_id": account_id, "profile": "schwab"},
        )
        assert response.status_code == 400


class TestGoals:
    """GL-03: goals API on the account-as-goal shape (tracker #939)."""

    @pytest.mark.asyncio
    async def test_create_virtual_goal_round_trip(
        self, authenticated_client: TestClient
    ) -> None:
        created = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Vacation",
                "target_amount": 300_000,
                "target_date": "2027-06-01",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["funding"] == "virtual"
        assert body["status"] == "active"
        assert body["balance"] == 0
        assert body["progress"] == 0.0
        assert body["monthly_need"] > 0  # derived from the target date

        listed = authenticated_client.get("/api/v1/finance/goals").json()
        assert [g["name"] for g in listed["items"]] == ["Vacation"]
        # The goal account stays out of the ordinary account list.
        accounts = authenticated_client.get("/api/v1/finance/accounts").json()
        assert accounts["total"] == 0

    @pytest.mark.asyncio
    async def test_flag_an_existing_account_as_a_linked_goal(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        savings = await FinanceService(async_db_session).create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="CHASE SAVINGS",
            account_type="savings",
            classification="asset",
            current_balance=65_900,
        )
        await async_db_session.commit()
        created = authenticated_client.post(
            "/api/v1/finance/goals",
            json={"account_id": savings.id, "target_amount": 1_200_000},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["funding"] == "linked"
        assert body["balance"] == 65_900
        assert body["name"] == "CHASE SAVINGS"

        # Removing the goal unflags; the account survives, visible.
        gone = authenticated_client.delete(f"/api/v1/finance/goals/{savings.id}")
        assert gone.status_code == 204
        assert authenticated_client.get("/api/v1/finance/goals").json()["total"] == 0
        accounts = authenticated_client.get("/api/v1/finance/accounts").json()
        assert [a["name"] for a in accounts["items"]] == ["CHASE SAVINGS"]

    @pytest.mark.asyncio
    async def test_update_and_status(self, authenticated_client: TestClient) -> None:
        goal_id = authenticated_client.post(
            "/api/v1/finance/goals",
            json={"name": "Roof", "target_amount": 1_200_000},
        ).json()["account_id"]
        patched = authenticated_client.patch(
            f"/api/v1/finance/goals/{goal_id}",
            json={"status": "paused", "monthly_contribution": 20_000},
        )
        assert patched.status_code == 200
        body = patched.json()
        assert body["status"] == "paused"
        assert body["monthly_contribution"] == 20_000
        assert body["monthly_need"] == 0  # paused goals ask nothing

        bad = authenticated_client.patch(
            f"/api/v1/finance/goals/{goal_id}", json={"status": "vibing"}
        )
        assert bad.status_code == 422

    @pytest.mark.asyncio
    async def test_contribute_and_delete_virtual(
        self, authenticated_client: TestClient
    ) -> None:
        goal_id = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Vacation",
                "target_amount": 300_000,
                "monthly_contribution": 25_000,
            },
        ).json()["account_id"]
        contributed = authenticated_client.post(
            f"/api/v1/finance/goals/{goal_id}/contribute",
            json={"amount": 120_000},
        )
        assert contributed.status_code == 200
        body = contributed.json()
        assert body["balance"] == 120_000
        assert body["progress"] == 0.4
        assert body["eta"] is not None  # declared rate -> a real date

        gone = authenticated_client.delete(f"/api/v1/finance/goals/{goal_id}")
        assert gone.status_code == 204
        assert authenticated_client.get("/api/v1/finance/goals").json()["total"] == 0

    @pytest.mark.asyncio
    async def test_eta_is_never_without_any_rate(
        self, authenticated_client: TestClient
    ) -> None:
        body = authenticated_client.post(
            "/api/v1/finance/goals",
            json={"name": "Someday", "target_amount": 500_000},
        ).json()
        assert body["eta"] is None

    @pytest.mark.asyncio
    async def test_contribute_to_linked_is_refused(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        savings = await FinanceService(async_db_session).create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="CHASE SAVINGS",
            account_type="savings",
            classification="asset",
        )
        await async_db_session.commit()
        authenticated_client.post(
            "/api/v1/finance/goals",
            json={"account_id": savings.id, "target_amount": 100_000},
        )
        refused = authenticated_client.post(
            f"/api/v1/finance/goals/{savings.id}/contribute",
            json={"amount": 5_000},
        )
        assert refused.status_code == 400

    @pytest.mark.asyncio
    async def test_unknown_goal_is_404(self, authenticated_client: TestClient) -> None:
        assert (
            authenticated_client.patch(
                "/api/v1/finance/goals/999999", json={"status": "paused"}
            ).status_code
            == 404
        )
        assert (
            authenticated_client.delete("/api/v1/finance/goals/999999").status_code
            == 404
        )

    @pytest.mark.asyncio
    async def test_auto_contribute_toggle_rides_patch(
        self, authenticated_client: TestClient
    ) -> None:
        body = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Vacation",
                "target_amount": 300_000,
                "monthly_contribution": 25_000,
            },
        ).json()
        assert body["auto_contribute"] is False  # opt-in, never assumed

        toggled = authenticated_client.patch(
            f"/api/v1/finance/goals/{body['account_id']}",
            json={"auto_contribute": True},
        ).json()
        assert toggled["auto_contribute"] is True
        # And it sticks without being resent.
        listed = authenticated_client.get("/api/v1/finance/goals").json()
        assert listed["items"][0]["auto_contribute"] is True

    @pytest.mark.asyncio
    async def test_percent_and_surplus_rules_ride_the_api(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        service = FinanceService(async_db_session)
        account = await service.create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        await service.create_recurring_stream(
            owner_user_id=acting_owner_user_id,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=820_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await async_db_session.commit()

        created = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Retire",
                "target_amount": 10_000_000,
                "contribution_kind": "percent_income",
                "contribution_pct_bps": 1_000,
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["contribution_kind"] == "percent_income"
        assert body["contribution_pct_bps"] == 1_000
        assert body["monthly_need"] == 82_000  # evaluated, not declared
        assert body["eta"] is not None  # the evaluated ask IS a rate

        # A status-only PATCH must not flatten the rule back to fixed.
        paused = authenticated_client.patch(
            f"/api/v1/finance/goals/{body['account_id']}",
            json={"status": "paused"},
        ).json()
        assert paused["contribution_kind"] == "percent_income"
        assert paused["contribution_pct_bps"] == 1_000

        surplus = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Snowball",
                "target_amount": 500_000,
                "contribution_kind": "surplus",
            },
        ).json()
        assert surplus["contribution_kind"] == "surplus"
        # Sole active goal: the sweep takes the whole surplus (capped at
        # its remaining target).
        assert surplus["monthly_need"] == 500_000

    @pytest.mark.asyncio
    async def test_percent_without_bps_is_422(
        self, authenticated_client: TestClient
    ) -> None:
        response = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Bad",
                "target_amount": 100_000,
                "contribution_kind": "percent_income",
            },
        )
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_goals_figures_survive_the_summary_response_schema(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        """The service computed goals_total, the typed response dropped it,
        and the header caption silently vanished while month_net (declared)
        still moved - the worst kind of half-truth. Pin the wire format."""
        service = FinanceService(async_db_session)
        account = await service.create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        await service.create_recurring_stream(
            owner_user_id=acting_owner_user_id,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=1_000_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await async_db_session.commit()
        authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Vacation",
                "target_amount": 300_000,
                "monthly_contribution": 27_273,
            },
        )
        stats = authenticated_client.get("/api/v1/finance/budget/summary").json()[
            "stats"
        ]
        assert stats["goals_total"] == 27_273
        assert stats["goals_count"] == 1
        assert stats["month_net"] == 1_000_000 - 27_273

    @pytest.mark.asyncio
    async def test_auto_contribute_can_ride_creation(
        self, authenticated_client: TestClient
    ) -> None:
        body = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Vacation",
                "target_amount": 300_000,
                "monthly_contribution": 25_000,
                "auto_contribute": True,
            },
        ).json()
        assert body["auto_contribute"] is True


class TestEnvelopes:
    """Virtual sub-accounts: credit / spend / auto-credit over the wire."""

    @pytest.mark.asyncio
    async def test_full_life_of_an_allowance(
        self, authenticated_client: TestClient
    ) -> None:
        created = authenticated_client.post(
            "/api/v1/finance/envelopes",
            json={"name": "Allowance", "monthly_credit": 4_000},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["balance"] == 0
        assert body["auto_credit"] is False

        credited = authenticated_client.post(
            f"/api/v1/finance/envelopes/{body['account_id']}/credit",
            json={"amount": 4_000, "note": "August"},
        ).json()
        assert credited["balance"] == 4_000

        spent = authenticated_client.post(
            f"/api/v1/finance/envelopes/{body['account_id']}/spend",
            json={"amount": 5_250, "note": "Roblox splurge"},
        ).json()
        assert spent["balance"] == -1_250  # negative survives the wire

        listed = authenticated_client.get("/api/v1/finance/envelopes").json()
        assert listed["total"] == 1
        # Envelope accounts never leak into the ordinary account list.
        assert authenticated_client.get("/api/v1/finance/accounts").json()["total"] == 0

        gone = authenticated_client.delete(
            f"/api/v1/finance/envelopes/{body['account_id']}"
        )
        assert gone.status_code == 204
        assert (
            authenticated_client.get("/api/v1/finance/envelopes").json()["total"] == 0
        )

    @pytest.mark.asyncio
    async def test_patch_updates_credit_and_auto(
        self, authenticated_client: TestClient
    ) -> None:
        body = authenticated_client.post(
            "/api/v1/finance/envelopes", json={"name": "Allowance"}
        ).json()
        patched = authenticated_client.patch(
            f"/api/v1/finance/envelopes/{body['account_id']}",
            json={"monthly_credit": 4_000, "auto_credit": True},
        ).json()
        assert patched["monthly_credit"] == 4_000
        assert patched["auto_credit"] is True

    @pytest.mark.asyncio
    async def test_unknown_envelope_is_404(
        self, authenticated_client: TestClient
    ) -> None:
        for response in (
            authenticated_client.post(
                "/api/v1/finance/envelopes/999999/credit", json={"amount": 100}
            ),
            authenticated_client.delete("/api/v1/finance/envelopes/999999"),
        ):
            assert response.status_code == 404


class TestBudgetStatDetails:
    @pytest.mark.asyncio
    async def test_details_back_the_header_cells(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        from datetime import date as date_cls

        svc = FinanceService(async_db_session)
        account = await svc.create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        await svc.create_recurring_stream(
            owner_user_id=acting_owner_user_id,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date_cls(2026, 9, 1),
            account_id=account.id,
        )
        # Two months of it: uncovered spending seen in only one month is
        # reported as a one-off, not amortized into the rate this cell
        # shows (see TestOneOffsDoNotBecomeARate).
        for month in (6, 7):
            await svc.create_transaction(
                account_id=account.id,
                amount=-9_000,
                txn_date=date_cls(2026, month, 2),
                owner_user_id=acting_owner_user_id,
                name="Cash",
            )
        await async_db_session.commit()

        response = authenticated_client.get("/api/v1/finance/budget/stat-details")

        assert response.status_code == 200
        body = response.json()
        assert [(r["label"], r["value"]) for r in body["income"]] == [
            ("Paycheck", 500_000)
        ]
        assert body["bills"] == []
        assert body["everything_else"][0]["label"] == "Uncategorized"
        # Data-only contract: the popup composes the window label itself.
        assert body["window_start"] < body["window_end"]


class TestBudgetOutlook:
    @pytest.mark.asyncio
    async def test_the_months_ride_the_wire(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        service = FinanceService(async_db_session)
        account = await service.create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        await service.create_recurring_stream(
            owner_user_id=acting_owner_user_id,
            name="Paycheck",
            direction="inflow",
            frequency="monthly",
            expected_amount=500_000,
            next_expected_date=date(2026, 8, 15),
            account_id=account.id,
        )
        await async_db_session.commit()

        body = authenticated_client.get(
            "/api/v1/finance/budget/outlook", params={"months": 4}
        ).json()
        assert body["total"] == 4
        entry = body["items"][1]
        for key in (
            "period_month",
            "income_due",
            "bills_due",
            "budgets",
            "goals",
            "envelopes",
            "month_net",
        ):
            assert key in entry
        assert entry["income_due"] == 500_000

    @pytest.mark.asyncio
    async def test_a_pause_goal_trim_survives_the_wire(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        """The pause tier never fired over the wire while months read
        fictionally positive; the honest equation made it fire and the
        typed trim response 500'd on the unfamiliar row. Pin both kinds."""
        service = FinanceService(async_db_session)
        account = await service.create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="Checking",
            account_type="checking",
            classification="asset",
        )
        await service.create_recurring_stream(
            owner_user_id=acting_owner_user_id,
            name="Rent",
            direction="outflow",
            frequency="monthly",
            expected_amount=200_000,
            next_expected_date=date(2026, 9, 1),
            account_id=account.id,
        )
        await service.create_virtual_goal(
            owner_user_id=acting_owner_user_id,
            name="Vacation",
            target_amount=300_000,
            monthly_contribution=25_000,
        )
        await async_db_session.commit()

        response = authenticated_client.get("/api/v1/finance/budget/summary")
        assert response.status_code == 200
        trims = response.json()["trims"]
        assert any(t.get("kind") == "pause_goal" for t in trims)
        pause = next(t for t in trims if t.get("kind") == "pause_goal")
        assert pause["label"] == "Vacation"
        assert pause["recovered"] == 25_000


REVIEW_QUEUE_URL = "/api/v1/finance/recurring/review-queue"


@pytest.mark.asyncio
async def test_review_queue_returns_only_bills_with_candidates(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """One batch call for a review session: the client sends the bills it
    considers past due, the server answers with each one's shortlist, and
    bills with nothing to offer are omitted entirely - the session never
    shows a no-candidates card."""
    from datetime import date

    from tests.services._finance_factories import seed_account, seed_stream

    svc = FinanceService(async_db_session)
    account = await seed_account(svc, owner_user_id=acting_owner_user_id)
    matchable = await seed_stream(
        svc,
        name="Citi",
        expected_amount=9_977,
        next_expected_date=date(2026, 8, 6),
        owner_user_id=acting_owner_user_id,
        account_id=account.id,
    )
    barren = await seed_stream(
        svc,
        name="Patreon",
        expected_amount=900,
        next_expected_date=date(2026, 8, 1),
        owner_user_id=acting_owner_user_id,
        account_id=account.id,
    )
    payment = await svc.create_transaction(
        account_id=account.id,
        amount=-11_790,
        txn_date=date(2026, 8, 7),
        owner_user_id=acting_owner_user_id,
        name="INTEREST CHARGED TO PUR PR-00/00/00.",
    )
    await async_db_session.commit()

    response = authenticated_client.get(
        f"{REVIEW_QUEUE_URL}?ids={matchable.id},{barren.id}"
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [e["stream_id"] for e in items] == [matchable.id]
    assert [c["id"] for c in items[0]["candidates"]] == [payment.id]


@pytest.mark.asyncio
async def test_review_queue_ignores_ids_that_are_not_yours(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    response = authenticated_client.get(f"{REVIEW_QUEUE_URL}?ids=999999")
    assert response.status_code == 200
    assert response.json()["items"] == []


class TestDerivedGoalTargets:
    """GL-16: a goal whose finish line is N months of expenses. The
    target is resolved from the month's committed figure on every read,
    so it moves when the bills do, without anyone editing the goal."""

    async def _bill(
        self,
        session: AsyncSession,
        owner_user_id: int | None,
        *,
        name: str,
        amount: int,
    ) -> None:
        await FinanceService(session).create_recurring_stream(
            owner_user_id=owner_user_id,
            name=name,
            direction="outflow",
            frequency="monthly",
            expected_amount=amount,
            next_expected_date=date(2026, 8, 1),
        )
        await session.commit()

    @pytest.mark.asyncio
    async def test_a_months_of_expenses_goal_sizes_itself(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        await self._bill(
            async_db_session, acting_owner_user_id, name="Rent", amount=300_000
        )
        created = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Emergency Fund",
                "target_rule": "months_of_expenses",
                "target_factor": 6,
            },
        )
        assert created.status_code == 201
        body = created.json()
        # Six months of a $3,000 month, computed server-side: the client
        # never sent an amount.
        assert body["target_amount"] == 1_800_000
        assert body["target_rule"] == "months_of_expenses"
        assert body["target_factor"] == 6

    @pytest.mark.asyncio
    async def test_the_target_moves_when_the_bills_do(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        await self._bill(
            async_db_session, acting_owner_user_id, name="Rent", amount=300_000
        )
        authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Emergency Fund",
                "target_rule": "months_of_expenses",
                "target_factor": 6,
            },
        )
        await self._bill(
            async_db_session, acting_owner_user_id, name="Car", amount=50_000
        )
        listed = authenticated_client.get("/api/v1/finance/goals").json()
        goal = listed["items"][0]
        # $3,500 a month now, and nobody touched the goal.
        assert goal["target_amount"] == 2_100_000
        assert goal["progress"] == 0.0

    @pytest.mark.asyncio
    async def test_a_fixed_goal_ignores_the_bills(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        created = authenticated_client.post(
            "/api/v1/finance/goals",
            json={"name": "Vacation", "target_amount": 300_000},
        )
        assert created.status_code == 201
        assert created.json()["target_rule"] == "fixed"
        assert created.json()["target_factor"] is None
        await self._bill(
            async_db_session, acting_owner_user_id, name="Rent", amount=300_000
        )
        listed = authenticated_client.get("/api/v1/finance/goals").json()
        assert listed["items"][0]["target_amount"] == 300_000

    @pytest.mark.asyncio
    async def test_a_relative_goal_with_nothing_to_size_against_is_refused(
        self, authenticated_client: TestClient
    ) -> None:
        """No bills, no budget lines: the target would be zero. Say why
        instead of storing a goal that reads as already reached."""
        refused = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Emergency Fund",
                "target_rule": "months_of_expenses",
                "target_factor": 6,
            },
        )
        assert refused.status_code == 400
        assert "bills" in refused.json()["detail"]

    @pytest.mark.asyncio
    async def test_switching_a_fixed_goal_to_a_relative_one(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        await self._bill(
            async_db_session, acting_owner_user_id, name="Rent", amount=300_000
        )
        created = authenticated_client.post(
            "/api/v1/finance/goals",
            json={"name": "Emergency Fund", "target_amount": 500_000},
        )
        goal_id = created.json()["account_id"]
        patched = authenticated_client.patch(
            f"/api/v1/finance/goals/{goal_id}",
            json={"target_rule": "months_of_expenses", "target_factor": 3},
        )
        assert patched.status_code == 200
        assert patched.json()["target_amount"] == 900_000
        # And back again: the fixed amount rules, the factor is dropped.
        back = authenticated_client.patch(
            f"/api/v1/finance/goals/{goal_id}",
            json={"target_rule": "fixed", "target_amount": 500_000},
        )
        assert back.json()["target_amount"] == 500_000
        assert back.json()["target_factor"] is None

    @pytest.mark.asyncio
    async def test_a_bad_factor_is_refused(
        self, authenticated_client: TestClient
    ) -> None:
        refused = authenticated_client.post(
            "/api/v1/finance/goals",
            json={"name": "Fund", "target_rule": "months_of_expenses"},
        )
        assert refused.status_code == 422

    @pytest.mark.asyncio
    async def test_the_preview_endpoint_answers_what_the_save_would_store(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        """The dialog previews through the same helper the write path
        uses, so the number on screen is the number that gets stored."""
        await self._bill(
            async_db_session, acting_owner_user_id, name="Rent", amount=300_000
        )
        preview = authenticated_client.get(
            "/api/v1/finance/goals/target-preview?factor=3&rule=months_of_expenses"
        )
        assert preview.status_code == 200
        assert preview.json() == {
            "expenses": 300_000,
            "target_amount": 900_000,
            "scope": [],
        }
        created = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Emergency Fund",
                "target_rule": "months_of_expenses",
                "target_factor": 3,
            },
        )
        assert created.json()["target_amount"] == preview.json()["target_amount"]

    @pytest.mark.asyncio
    async def test_an_unknown_rule_is_refused_not_answered_with_zero(
        self, authenticated_client: TestClient
    ) -> None:
        """A preview that silently returns 0 reads as 'nothing to size
        against' - a real answer to a question nobody asked."""
        refused = authenticated_client.get(
            "/api/v1/finance/goals/target-preview?factor=3&rule=vibes"
        )
        assert refused.status_code == 422

    @pytest.mark.asyncio
    async def test_a_scoped_goal_ignores_another_accounts_bills(
        self,
        authenticated_client: TestClient,
        async_db_session: AsyncSession,
        acting_owner_user_id: int | None,
    ) -> None:
        """The reason scope exists: a second checking account's bills are
        not this household's run rate."""
        service = FinanceService(async_db_session)
        ours = await service.create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="TOTAL CHECKING",
            account_type="checking",
            classification="asset",
            current_balance=0,
        )
        theirs = await service.create_manual_account(
            owner_user_id=acting_owner_user_id,
            name="OTHER CHECKING",
            account_type="checking",
            classification="asset",
            current_balance=0,
        )
        await async_db_session.commit()
        for account, amount, name in (
            (ours, 300_000, "Rent"),
            (theirs, 900_000, "Not ours"),
        ):
            await service.create_recurring_stream(
                owner_user_id=acting_owner_user_id,
                name=name,
                direction="outflow",
                frequency="monthly",
                expected_amount=amount,
                next_expected_date=date(2026, 8, 1),
                account_id=account.id,
            )
        await async_db_session.commit()

        scoped = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Emergency Fund",
                "target_rule": "months_of_expenses",
                "target_factor": 3,
                "target_scope": [ours.id],
            },
        )
        assert scoped.status_code == 201
        body = scoped.json()
        assert body["target_amount"] == 900_000  # 3 x $3,000, not 3 x $12,000
        assert body["target_scope"] == [ours.id]

        wide = authenticated_client.post(
            "/api/v1/finance/goals",
            json={
                "name": "Everything Fund",
                "target_rule": "months_of_expenses",
                "target_factor": 3,
            },
        )
        assert wide.json()["target_amount"] == 3_600_000
        assert wide.json()["target_scope"] == []


@pytest.mark.asyncio
async def test_secured_debt_link_round_trip(
    authenticated_client: TestClient,
) -> None:
    """FW-04 acceptance: link the mortgage to the property as first lien,
    read it back on the account list, unlink and it is gone."""
    house = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "House Bedner",
            "account_type": "property",
            "classification": "asset",
        },
    ).json()
    mortgage = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "Citizens Mortgage",
            "account_type": "loan",
            "classification": "liability",
        },
    ).json()

    linked = authenticated_client.patch(
        f"/api/v1/finance/accounts/{mortgage['id']}/secured-by",
        json={"secured_by_account_id": house["id"], "lien_position": 1},
    )
    assert linked.status_code == 200
    assert linked.json()["secured_by_account_id"] == house["id"]
    assert linked.json()["lien_position"] == 1

    rows = authenticated_client.get("/api/v1/finance/accounts").json()["items"]
    row = next(r for r in rows if r["id"] == mortgage["id"])
    assert row["liability"]["secured_by_account_id"] == house["id"]

    unlinked = authenticated_client.patch(
        f"/api/v1/finance/accounts/{mortgage['id']}/secured-by",
        json={"secured_by_account_id": None},
    )
    assert unlinked.status_code == 200
    assert unlinked.json()["secured_by_account_id"] is None
    assert unlinked.json()["lien_position"] is None


@pytest.mark.asyncio
async def test_a_lien_on_a_non_property_is_refused(
    authenticated_client: TestClient,
) -> None:
    checking = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "Checking",
            "account_type": "checking",
            "classification": "asset",
        },
    ).json()
    mortgage = authenticated_client.post(
        "/api/v1/finance/accounts",
        json={
            "name": "Citizens Mortgage",
            "account_type": "loan",
            "classification": "liability",
        },
    ).json()

    refused = authenticated_client.patch(
        f"/api/v1/finance/accounts/{mortgage['id']}/secured-by",
        json={"secured_by_account_id": checking["id"], "lien_position": 1},
    )
    assert refused.status_code == 400
    assert "not a property" in refused.json()["detail"]


async def _seed_change_fixture(service, owner_user_id):
    account = await service.create_manual_account(
        owner_user_id=owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    category = await service.get_or_create_category_from_hint(
        "Food & Dining:Eating Out"
    )
    txn = await service.create_transaction(
        owner_user_id=owner_user_id,
        account_id=account.id,
        amount=-897,
        txn_date=date(2026, 6, 10),
        name="Shelly's Deli",
    )
    return txn, category


@pytest.mark.asyncio
async def test_pending_change_approve_round_trip(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """FW-05 acceptance: a proposal lists as pending with its
    human-readable display, approval executes the mutation, and the
    resolved state reads back."""
    txn, category = await _seed_change_fixture(
        FinanceService(async_db_session), acting_owner_user_id
    )
    await async_db_session.commit()

    proposed = authenticated_client.post(
        "/api/v1/finance/changes",
        json={
            "change_type": "transaction.categorize",
            "payload": {"transaction_id": txn.id, "category_id": category.id},
        },
    )
    assert proposed.status_code == 200, proposed.text
    change = proposed.json()
    assert change["status"] == "pending"
    assert change["title"] == "Categorize a transaction"
    assert any("Shelly" in row["value"] for row in change["display"])

    listed = authenticated_client.get("/api/v1/finance/changes").json()
    assert [c["id"] for c in listed["items"]] == [change["id"]]

    approved = authenticated_client.post(
        f"/api/v1/finance/changes/{change['id']}/approve"
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    await async_db_session.refresh(txn)
    assert txn.category_id == category.id


@pytest.mark.asyncio
async def test_pending_change_reject_keeps_the_audit_row(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    txn, category = await _seed_change_fixture(
        FinanceService(async_db_session), acting_owner_user_id
    )
    await async_db_session.commit()

    change = authenticated_client.post(
        "/api/v1/finance/changes",
        json={
            "change_type": "transaction.categorize",
            "payload": {"transaction_id": txn.id, "category_id": category.id},
        },
    ).json()

    rejected = authenticated_client.post(
        f"/api/v1/finance/changes/{change['id']}/reject"
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    assert authenticated_client.get("/api/v1/finance/changes").json()["items"] == []
    trail = authenticated_client.get(
        "/api/v1/finance/changes", params={"status": "rejected"}
    ).json()["items"]
    assert [c["id"] for c in trail] == [change["id"]]

    await async_db_session.refresh(txn)
    assert txn.category_id is None
    resolved_again = authenticated_client.post(
        f"/api/v1/finance/changes/{change['id']}/approve"
    )
    assert resolved_again.status_code == 400


@pytest.mark.asyncio
async def test_batch_approve_with_a_veto(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    service = FinanceService(async_db_session)
    account = await service.create_manual_account(
        owner_user_id=acting_owner_user_id,
        name="Checking",
        account_type="checking",
        classification="asset",
    )
    category = await service.get_or_create_category_from_hint("Food & Dining:Groceries")
    txns = [
        await service.create_transaction(
            owner_user_id=acting_owner_user_id,
            account_id=account.id,
            amount=-1_000 - i,
            txn_date=date(2026, 8, 1 + i),
            name=f"Store {i}",
        )
        for i in range(3)
    ]
    rows = await service.propose_many_changes(
        "transaction.categorize",
        [{"transaction_id": t.id, "category_id": category.id} for t in txns],
        owner_user_id=acting_owner_user_id,
    )
    batch_id = rows[0].batch_id
    await async_db_session.commit()

    listed = authenticated_client.get("/api/v1/finance/changes").json()["items"]
    assert {c["batch_id"] for c in listed} == {batch_id}

    resolved = authenticated_client.post(
        f"/api/v1/finance/changes/batch/{batch_id}/approve",
        json={"exclude_ids": [rows[1].id]},
    )
    assert resolved.status_code == 200
    assert resolved.json()["approved"] == 2
    assert resolved.json()["rejected"] == 1

    await async_db_session.refresh(txns[0])
    await async_db_session.refresh(txns[1])
    assert txns[0].category_id == category.id
    assert txns[1].category_id is None


@pytest.mark.asyncio
async def test_an_executor_crash_keeps_the_recorded_error(
    authenticated_client: TestClient,
    async_db_session: AsyncSession,
    acting_owner_user_id: int | None,
) -> None:
    """A non-domain executor failure (not ValueError) must still land the
    row's recorded error - losing it to a rollback erases exactly the
    audit detail the card shows - and must not leak internals."""
    from pydantic import BaseModel, ConfigDict

    from app.services.finance.domains.writes import registry

    class _BoomPayload(BaseModel):
        model_config = ConfigDict(extra="forbid")
        anything: int

    async def _boom(db, payload, owner_user_id):
        raise RuntimeError("secret internal detail")

    async def _describe(db, payload, owner_user_id):
        from app.services.finance.schemas import ChangeDisplayRow

        return [ChangeDisplayRow(label="Anything", value=str(payload.anything))]

    registry.register(
        registry.ChangeExecutor(
            change_type="test.boom",
            title="Boom",
            payload_model=_BoomPayload,
            execute=_boom,
            describe=_describe,
        )
    )
    try:
        change = authenticated_client.post(
            "/api/v1/finance/changes",
            json={"change_type": "test.boom", "payload": {"anything": 1}},
        ).json()

        crashed = authenticated_client.post(
            f"/api/v1/finance/changes/{change['id']}/approve"
        )

        assert crashed.status_code == 500
        assert "secret internal detail" not in crashed.text
        row = authenticated_client.get(f"/api/v1/finance/changes/{change['id']}").json()
        assert row["status"] == "pending"
        assert "secret internal detail" in (row["error"] or "")
    finally:
        registry._EXECUTORS.pop("test.boom", None)
