"""The Overseer AI page's Costs section: the money view beside Usage, in four
tabs. Overview (a month in figures and charts), Users (who it was spent
on), Projections (where the last 90 days say it is heading) and Breakdown
(every action, grouped by the feature it pays for)."""

from datetime import date, datetime
import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip(
    "app.services.ai.domains.spend", reason="costs need an AI persistence backend"
)

from app.components.web_frontend import overseer_ai_costs  # noqa: E402
from app.services.ai.domains.spend.schemas import (  # noqa: E402
    ActionSpend,
    ModelSpend,
    SpendLedger,
)
from app.services.system.models import ComponentStatus  # noqa: E402
from tests.web.dom import one, select, text  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

PAGE = "/overseer/services/ai"

LEDGER = SpendLedger(
    # Every day's spend, voice included: $3.50 of model calls and $1.00 of
    # voice.
    daily={date(2026, 9, 3): 1.5, date(2026, 9, 5): 3.0},
    actions={
        "stream_chat:finance-assistant": ActionSpend(calls=3, cost=1.0),
        "chat:finance-assistant": ActionSpend(calls=1, cost=0.5),
        "document_extraction": ActionSpend(calls=2, cost=2.0),
    },
    users=2,
    models=[
        ModelSpend(model_id="gpt-x", title="GPT X", cost=3.0),
        ModelSpend(model_id="tiny", title=None, cost=0.5),
    ],
    voice={"Transcription": 0.25, "Speech": 0.75},
)

USERS: dict[str | None, dict[str, ActionSpend]] = {
    "7": {
        "stream_chat:finance-assistant": ActionSpend(calls=3, cost=1.2),
        "chat:finance-assistant": ActionSpend(calls=1, cost=0.3),
    },
    "api-user": {"document_extraction": ActionSpend(calls=2, cost=2.0)},
    None: {"sentiment": ActionSpend(calls=4, cost=0.1)},
}


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    asked: list[tuple[datetime, datetime]] = []

    async def ledger(db: Any, start: datetime, end: datetime) -> SpendLedger:
        asked.append((start, end))
        return LEDGER

    async def first_call(db: Any) -> datetime:
        return datetime(2026, 8, 20)

    async def user_spend(
        db: Any, start: datetime, end: datetime
    ) -> dict[str | None, dict[str, ActionSpend]]:
        return USERS

    async def user_names(db: Any, ids: list[str]) -> dict[str, str]:
        return {"7": "Ada Lovelace"} if "7" in ids else {}

    monkeypatch.setattr(overseer_ai_costs, "ledger", ledger)
    monkeypatch.setattr(overseer_ai_costs, "first_call", first_call)
    monkeypatch.setattr(overseer_ai_costs, "user_spend", user_spend)
    monkeypatch.setattr(overseer_ai_costs, "user_names", user_names)
    monkeypatch.setattr(overseer_ai_costs, "today", lambda: date(2026, 9, 10))
    ai = ComponentStatus(name="ai", message="AI", metadata={"engine": "pydantic-ai"})
    sign_in(app, monkeypatch, status_with(services=[ai]))
    test_client = TestClient(app)
    test_client.asked = asked  # type: ignore[attr-defined]
    return test_client


def _costs(client: TestClient, query: str = "") -> str:
    response = client.get(f"{PAGE}/costs" + (f"?{query}" if query else ""))
    assert response.status_code == 200, response.text
    return response.text


def _figures(html: str) -> dict[str, str]:
    return {
        text(one(cell, "dt")): text(select(cell, "dd")[0])
        for cell in select(html, "#ai-cost-figures > div")
    }


def _rows(html: str, table: str) -> list[list[str]]:
    return [
        [text(td) for td in select(tr, "td")]
        for tr in select(html, f"#{table} tbody tr")
    ]


# --- Tabs -------------------------------------------------------------------


def test_four_tabs_and_the_month_rides_along(client: TestClient) -> None:
    html = _costs(client, "month=2026-08")
    tabs = {text(a): a for a in select(html, "#ai-cost-tabs a")}
    assert list(tabs) == ["Overview", "Users", "Projections", "Breakdown"]
    assert tabs["Overview"].get("aria-current") == "page"
    assert "month=2026-08" in tabs["Users"].get("href")
    assert "tab=users" in tabs["Users"].get("href")


def test_the_month_chips_keep_the_tab(client: TestClient) -> None:
    chips = [
        a.get("href")
        for a in select(_costs(client, "tab=breakdown"), "#ai-cost-months a")
    ]
    assert chips and all("tab=breakdown" in href for href in chips)


def test_an_unknown_tab_is_the_overview(client: TestClient) -> None:
    html = _costs(client, "tab=nope")
    assert one(html, "#ai-cost-tabs [aria-current=page]").get("href").endswith("costs")


# --- Overview ---------------------------------------------------------------


def test_the_month_in_figures(client: TestClient) -> None:
    figures = _figures(_costs(client))
    assert figures["Total spend"] == "$4.50"
    assert figures["Daily average"] == "$0.45"  # ten days into September
    assert figures["Cost per user"] == "$2.25"
    assert figures["Top feature"] == "$2.00"
    assert "$13.50" in text(one(_costs(client), "#ai-cost-figures"))  # projected


def test_a_month_is_picked_from_the_ledgers_span(client: TestClient) -> None:
    chips = [a.get("href") for a in select(_costs(client), "#ai-cost-months a")]
    assert any("month=2026-09" in c for c in chips)
    assert any("month=2026-08" in c for c in chips)
    _costs(client, "month=2026-08")
    start, end = client.asked[-1]  # type: ignore[attr-defined]
    assert (start, end) == (datetime(2026, 8, 1), datetime(2026, 9, 1))


def test_features_group_an_agents_calls(client: TestClient) -> None:
    rows = [text(li) for li in select(_costs(client), "#ai-cost-features li")]
    assert "Document Extraction" in rows[0] and "$2.00" in rows[0]
    assert "Finance Assistant" in rows[1] and "$1.50" in rows[1]


def test_models_and_voice_split_the_money(client: TestClient) -> None:
    html = _costs(client)
    assert one(html, "#chart-ai-cost-models canvas") is not None
    split = text(one(html, "#ai-cost-split"))
    assert "Model calls" in split and "Transcription" in split and "Speech" in split


def test_every_day_of_the_month_is_on_the_chart(client: TestClient) -> None:
    data = json.loads(text(one(_costs(client), "#chart-ai-cost-daily-data")))
    assert data["format"] == "money"
    assert len(data["labels"]) == 10  # to today, not the month's end
    assert data["series"][0]["values"][2] == 1.5


# --- Users ------------------------------------------------------------------


def test_top_spenders_by_name_where_the_user_is_known(client: TestClient) -> None:
    rows = _rows(_costs(client, "tab=users"), "ai-cost-users")
    assert rows[0][1] == "api-user" and rows[0][2] == "$2.00"
    assert rows[1][1] == "Ada Lovelace" and rows[1][2] == "$1.50"
    assert rows[1][3] == "4" and rows[1][4] == "$0.38"  # 1.50 over 4 calls
    assert rows[1][5] == "Finance Assistant"
    assert rows[2][1] == "No user (background)"


# --- Projections --------------------------------------------------------------


def test_projections_read_the_last_90_days(client: TestClient) -> None:
    html = _costs(client, "tab=projections")
    start, end = client.asked[-1]  # type: ignore[attr-defined]
    assert (start, end) == (datetime(2026, 6, 13), datetime(2026, 9, 11))
    assert not select(html, "#ai-cost-months")  # forward-looking: no month
    figures = _figures(html)
    # $4.50 over 90 days is $0.05 a day.
    assert figures["6 months forecast"] == "$9.00"
    assert figures["Month-end forecast"] == "$1.50"
    assert figures["Annual run rate"] == "$18.25"
    assert figures["Week over week"] == "+100.0%"  # $3.00 vs $1.50


def test_the_horizon_is_chosen(client: TestClient) -> None:
    html = _costs(client, "tab=projections&horizon=12")
    assert _figures(html)["12 months forecast"] == "$18.00"


def test_each_feature_is_projected(client: TestClient) -> None:
    rows = _rows(_costs(client, "tab=projections"), "ai-cost-forecast")
    assert rows[0][0] == "Document Extraction"
    assert rows[0][1] == "$0.02"  # $2.00 over 90 days, a day
    assert rows[0][3] == "$8.11"  # a year


# --- Breakdown ----------------------------------------------------------------


def test_every_action_under_its_feature(client: TestClient) -> None:
    html = _costs(client, "tab=breakdown")
    rows = _rows(html, "ai-cost-breakdown")
    groups = [tr for tr in select(html, "#ai-cost-breakdown tbody tr[data-group]")]
    assert len(groups) == 2
    assert rows[0][:2] == ["Document Extraction", "$2.00"] and rows[0][4] == "57.1%"
    assert rows[2][:3] == ["Finance Assistant", "$1.50", "4"]
    assert rows[3][0] == "stream_chat:finance-assistant" and rows[3][1] == "$1.00"
    assert rows[4][0] == "chat:finance-assistant"
