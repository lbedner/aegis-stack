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

from fastapi.testclient import TestClient
import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.finance.finance_service import FinanceService


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

    from app.services.finance import networth_service

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
    await networth_service.recompute_snapshots(
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

    from app.services.finance import import_service
    from app.services.finance.importers.ofx import parse_ofx

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
    result = await import_service.ingest_transactions(
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

    from app.components.backend.api.finance import router as finance_router_module

    @asynccontextmanager
    async def _session():
        yield async_db_session

    monkeypatch.setattr(finance_router_module, "_job_session", _session)

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

    from app.components.backend.api.finance import router as finance_router_module

    @asynccontextmanager
    async def _session():
        yield async_db_session

    monkeypatch.setattr(finance_router_module, "_job_session", _session)

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

    from app.components.backend.api.finance import router as finance_router_module

    @asynccontextmanager
    async def _session():
        yield async_db_session

    monkeypatch.setattr(finance_router_module, "_job_session", _session)

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
    authenticated_client.post(
        "/api/v1/finance/recurring",
        json={
            "name": "Netflix",
            "direction": "outflow",
            "frequency": "monthly",
            "expected_amount": 1599,
            "next_expected_date": "2026-08-01",
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
    assert result == {"items": [], "total": 0}


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

    from app.services.finance.finance_service import FinanceService
    from app.services.finance.models import FinanceRecurringStream

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

    from app.services.finance.finance_service import FinanceService
    from app.services.finance.models import FinanceRecurringStream

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
    from app.services.finance.finance_service import FinanceService
    from app.services.finance.models import FinanceRecurringStream

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

    from app.services.finance.finance_service import FinanceService
    from app.services.finance.models import FinanceRecurringStream

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
    groceries = await FinanceService(
        async_db_session
    ).get_or_create_category_from_hint("Food:Groceries")
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
