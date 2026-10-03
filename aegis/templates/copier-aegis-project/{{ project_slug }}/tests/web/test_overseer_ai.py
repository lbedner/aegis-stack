"""The Overseer AI page, phase one: whether the service is set up and
what it has done (Overview), and every provider with what it needs
(Providers). Read-only; keys still live in ``.env``."""

from importlib.util import find_spec
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("app.services.ai", reason="no AI service in this stack")

from app.components.web_frontend import overseer_ai_catalog, ranges  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.services.ai.models import PROVIDERS  # noqa: E402
from app.services.system.models import ComponentStatus  # noqa: E402
from tests.web.dom import checked, one, select, text, triggers  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

PAGE = "/overseer/services/ai"
# A 1x1 transparent PNG.
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
    "60e6kgAAAABJRU5ErkJggg=="
)
METADATA: dict[str, Any] = {
    "engine": "pydantic-ai",
    "enabled": True,
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
    "total_conversations": 12,
    "total_messages": 340,
    "unique_users": 3,
    "total_tokens": 125_000,
    "total_cost": 1.2345,
    "configuration_valid": True,
    "validation_errors": [],
    "persistence": "sqlite",
}


def _current(**overrides: Any) -> SimpleNamespace:
    """What ``get_current_config`` answers: the model in effect."""
    return SimpleNamespace(
        **{
            "provider": "anthropic",
            "model": "claude-haiku-4-5-20251001",
            "temperature": 0.7,
            "max_tokens": 1000,
            "in_catalog": False,
            "source": "env",
            "override_updated_at": None,
            "env_model": "claude-haiku-4-5-20251001",
            "context_window": None,
            "input_price": None,
            "output_price": None,
        }
        | overrides
    )


def _client(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict[str, Any] | None = None,
    current: SimpleNamespace | None = None,
) -> TestClient:
    from app.components.web_frontend import overseer_ai
    from app.services.ai.domains.llm import provider_management

    async def get_current_config() -> SimpleNamespace:
        return current or _current()

    monkeypatch.setattr(overseer_ai, "get_current_config", get_current_config)
    monkeypatch.setattr(
        provider_management, "check_provider_dependency_installed", lambda p: True
    )
    for spec in PROVIDERS.values():
        if spec.env_var in type(settings).model_fields:
            monkeypatch.setattr(settings, spec.env_var, None)
    monkeypatch.setattr(settings, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    ai = ComponentStatus(name="ai", message="AI", metadata=metadata or METADATA)
    sign_in(app, monkeypatch, status_with(services=[ai]))
    return TestClient(app)


def _get(client: TestClient, section: str = "") -> str:
    response = client.get(PAGE + (f"/{section}" if section else ""))
    assert response.status_code == 200, response.text
    return response.text


def _facts(html: str, card: str) -> dict[str, str]:
    dl = one(html, f"#{card} dl")
    return dict(
        zip(
            [text(dt) for dt in select(dl, "dt")],
            [text(dd) for dd in select(dl, "dd")],
            strict=True,
        )
    )


def test_sections(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    html = _get(_client(app, monkeypatch))
    from app.components.web_frontend.overseer_ai import PERSISTED

    activity = ["Usage", "Costs", "Sentiment"] if PERSISTED else []
    from app.components.web_frontend.overseer_ai_common import HAS_RAG

    agents = ["Agents", "Memory"] if PERSISTED else []
    knowledge = ["Knowledge", "Search"] if HAS_RAG else []
    from app.components.web_frontend.overseer_ai_common import HAS_VOICE

    voice = ["Voice"] if HAS_VOICE else []
    catalog = ["Catalog"] if PERSISTED else []
    assert [text(a) for a in select(html, "#overseer-subnav nav a")] == [
        "Overview",
        "Chat",
        *activity,
        *agents,
        *knowledge,
        *voice,
        *catalog,
        "Providers",
    ]


def test_the_overview_counts_what_the_service_has_done(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    figures = {
        text(one(cell, "dt")): text(select(cell, "dd")[0])
        for cell in select(_get(_client(app, monkeypatch)), "#ai-figures > div")
    }
    assert figures == {
        "Conversations": "12",
        "Messages": "340",
        "Tokens": "125,000",
        "Cost": "$1.23",
    }


def test_the_active_model_says_where_it_comes_from(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = _facts(_get(_client(app, monkeypatch)), "ai-model")
    assert facts["Provider"] == "Anthropic"
    assert facts["Model"] == "claude-haiku-4-5-20251001"
    assert facts["Set by"] == "AI_MODEL in .env"
    assert facts["In the catalog"] == "No"


def test_a_stored_choice_is_named_as_such(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(app, monkeypatch, current=_current(source="override"))
    facts = _facts(_get(client), "ai-model")
    assert "llm use" in facts["Set by"]


def test_configuration_problems_are_listed(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = METADATA | {
        "configuration_valid": False,
        "validation_errors": ["Missing API key for openai provider."],
    }
    html = _get(_client(app, monkeypatch, metadata=broken))
    assert "Missing API key for openai" in text(one(html, "#ai-problems"))


def test_providers_say_what_each_needs(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _get(_client(app, monkeypatch), "providers")
    rows = {text(select(r, "td")[0]): r for r in select(html, "#ai-providers tbody tr")}
    assert "Current" in text(rows["Anthropic"])
    assert "Needs a key" in text(rows["OpenAI"])
    assert "OPENAI_API_KEY" in text(rows["OpenAI"])
    assert "Needs a key" not in text(rows["Pollinations"])


def test_a_provider_links_to_where_a_key_comes_from(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _get(_client(app, monkeypatch), "providers")
    links = [a.get("href") for a in select(html, "#ai-providers tbody a")]
    assert "https://platform.openai.com/api-keys" in links


persisted = pytest.mark.skipif(
    find_spec("app.services.ai.domains.chat.sentiment") is None,
    reason="usage and sentiment need an AI persistence backend",
)

USAGE: dict[str, Any] = {
    "total_tokens": 150_000,
    "input_tokens": 120_000,
    "output_tokens": 30_000,
    "total_cost": 2.5,
    "total_requests": 40,
    "success_rate": 97.5,
    "models": [
        {
            "model_id": "claude-haiku-4-5",
            "model_title": "Claude Haiku 4.5",
            "vendor": "anthropic",
            "requests": 30,
            "tokens": 100_000,
            "cost": 1.5,
            "percentage": 66.7,
        },
        {
            "model_id": "gpt-4o-mini",
            "model_title": None,
            "vendor": "openai",
            "requests": 10,
            "tokens": 50_000,
            "cost": 1.0,
            "percentage": 33.3,
        },
    ],
    "recent_activity": [
        {
            "timestamp": "2026-09-29T20:00:00",
            "model": "claude-haiku-4-5",
            "input_tokens": 900,
            "output_tokens": 120,
            "cost": 0.002,
            "success": False,
            "action": "chat",
            "duration_ms": 1830,
            "cache_read_tokens": 400,
            "cache_write_tokens": None,
            "tool_calls": 2,
            "user_id": "7",
            "error_message": "overloaded_error",
        },
    ],
}


def _usage(monkeypatch: pytest.MonkeyPatch, seen: list[Any] | None = None) -> None:
    from app.components.web_frontend import overseer_ai

    async def usage_stats(**kwargs: Any) -> dict[str, Any]:
        if seen is not None:
            seen.append(kwargs)
        return USAGE

    monkeypatch.setattr(overseer_ai, "usage_stats", usage_stats)


@persisted
def test_usage_totals_for_the_window(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(app, monkeypatch)
    _usage(monkeypatch)
    figures = {
        text(one(cell, "dt")): text(select(cell, "dd")[0])
        for cell in select(_get(client, "usage"), "#ai-usage-figures > div")
    }
    assert figures["Requests"] == "40"
    assert "Cost" not in figures  # the money lives in Costs
    assert figures["Success rate"] == "97.5%"


@persisted
def test_the_window_chips_narrow_the_range(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    client = _client(app, monkeypatch)
    _usage(monkeypatch, seen)
    client.get(f"{PAGE}/usage?days=7")
    assert seen[-1]["start_time"] is not None
    client.get(f"{PAGE}/usage?days={ranges.ALL}")
    assert seen[-1]["start_time"] is None


@persisted
def test_the_window_row_is_the_apps_one(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same chips as every other time-window row (``ranges.WINDOWS``),
    a week unless the address says otherwise."""
    client = _client(app, monkeypatch)
    _usage(monkeypatch)
    html = _get(client, "usage?days=bogus")
    assert [text(label) for label in select(html, "#ai-usage-window label")] == [
        label for _days, label in ranges.WINDOWS
    ]
    assert checked(html, '#ai-usage-window input[name="days"]') == ["7"]


@persisted
def test_each_model_has_its_share(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(app, monkeypatch)
    _usage(monkeypatch)
    rows = select(_get(client, "usage"), "#ai-models tbody tr")
    assert "Claude Haiku 4.5" in text(rows[0]) and "66.7%" in text(rows[0])
    assert "gpt-4o-mini" in text(rows[1])


@persisted
def test_a_recent_call_expands_to_its_detail(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(app, monkeypatch)
    _usage(monkeypatch)
    html = _get(client, "usage")
    detail = text(one(html, "#ai-recent [data-detail]"))
    assert "overloaded_error" in detail and "1.8s" in detail and "2" in detail


@persisted
def test_sentiment_is_a_chart_and_the_negatives(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from app.components.web_frontend import overseer_ai

    async def sentiment_stats() -> dict[str, Any]:
        return {
            "enabled": True,
            "total": 5,
            "distribution": {"positive": 3, "neutral": 1, "negative": 1},
            "performance": {},
            "average_score": 0.42,
            "recent_negatives": [
                {
                    "conversation_id": "c1",
                    "overall_sentiment": "negative",
                    "summary": "Could not find the invoice",
                    "created_at": "2026-09-29T19:00:00",
                }
            ],
        }

    client = _client(app, monkeypatch)
    monkeypatch.setattr(overseer_ai, "sentiment_stats", sentiment_stats)
    html = _get(client, "sentiment")
    data = json.loads(text(one(html, "#chart-ai-sentiment-data")))
    assert data["labels"] == ["Positive", "Neutral", "Negative"]
    assert "Could not find the invoice" in text(one(html, "#ai-negatives"))


@persisted
def test_sentiment_says_when_scoring_is_off(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend import overseer_ai

    async def sentiment_stats() -> dict[str, Any]:
        return {
            "enabled": False,
            "total": 0,
            "distribution": {},
            "performance": {},
            "average_score": 0.0,
            "recent_negatives": [],
        }

    client = _client(app, monkeypatch)
    monkeypatch.setattr(overseer_ai, "sentiment_stats", sentiment_stats)
    assert "AI_SENTIMENT_ENABLED" in text(
        one(_get(client, "sentiment"), "#ai-sentiment")
    )


@persisted
async def test_usage_rows_wear_their_vendors_mark(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    async_client_with_db: TestClient,
    async_db_session: Any,
) -> None:
    """By model and each recent call carry the vendor's logo; a model the
    catalog cannot place keeps the initial."""
    from app.services.ai.models.llm.llm_org import LLMOrg

    async_db_session.add(LLMOrg(slug="anthropic", name="Anthropic", icon_b64=PNG_B64))
    await async_db_session.commit()
    _client(app, monkeypatch)
    _usage(monkeypatch)
    html = _get(async_client_with_db, "usage")
    by_model = select(html, "#ai-models tbody tr")
    mark = "/partials/overseer/ai/icons/anthropic"
    assert one(by_model[0], "img").get("src") == mark
    assert select(by_model[1], "[data-avatar]")
    recent = select(html, "#ai-recent tbody tr")[0]
    assert one(recent, "img").get("src") == mark


@persisted
async def test_a_provider_wears_its_labs_mark(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    async_client_with_db: TestClient,
    async_db_session: Any,
) -> None:
    from app.services.ai.models.llm.llm_org import LLMOrg

    async_db_session.add(LLMOrg(slug="anthropic", name="Anthropic", icon_b64=PNG_B64))
    await async_db_session.commit()
    _client(app, monkeypatch)
    html = _get(async_client_with_db, "providers")
    rows = {text(select(r, "td")[0]): r for r in select(html, "#ai-providers tbody tr")}
    assert (
        one(rows["Anthropic"], "img").get("src")
        == "/partials/overseer/ai/icons/anthropic"
    )
    assert one(rows["OpenAI"], "[data-avatar]").get("data-avatar") == "O"


@persisted
async def test_the_icon_route_serves_the_mark_cached(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    async_client_with_db: TestClient,
    async_db_session: Any,
) -> None:
    import base64

    from app.services.ai.models.llm.llm_org import LLMOrg

    async_db_session.add(LLMOrg(slug="anthropic", name="Anthropic", icon_b64=PNG_B64))
    await async_db_session.commit()
    _client(app, monkeypatch)
    response = async_client_with_db.get("/partials/overseer/ai/icons/anthropic")
    assert response.status_code == 200 and response.content == base64.b64decode(PNG_B64)
    assert "max-age" in response.headers["cache-control"]
    again = async_client_with_db.get(
        "/partials/overseer/ai/icons/anthropic",
        headers={"if-none-match": response.headers["etag"]},
    )
    assert again.status_code == 304
    assert (
        async_client_with_db.get("/partials/overseer/ai/icons/groq").status_code == 404
    )


def _catalog(
    monkeypatch: pytest.MonkeyPatch,
    seen: list[Any] | None = None,
    vendors: list[Any] | None = [],  # noqa: B006 - None: read the real ones
) -> None:
    from app.components.web_frontend import overseer_ai_catalog
    from app.services.ai.domains.llm.catalog import LLMListResult

    async def list_models(**kwargs: Any) -> list[LLMListResult]:
        if seen is not None:
            seen.append(kwargs)
        return [
            LLMListResult(
                model_id="claude-haiku-4-5-20251001",
                title="Claude Haiku 4.5",
                vendor="anthropic",
                family="claude",
                color="#D97757",
                context_window=200_000,
                input_price=1.0,
                output_price=5.0,
                released_on="2025-10-01",
                lab="Anthropic",
                lab_icon_b64=PNG_B64,
            ),
            LLMListResult(
                model_id="openai/gpt-4o-mini",
                title="GPT-4o mini",
                vendor="openai",
                family=None,
                color="#10A37F",
                context_window=128_000,
                input_price=0.15,
                output_price=0.6,
                released_on=None,
            ),
            LLMListResult(
                model_id="openai/gpt-realtime",
                title="GPT Realtime",
                vendor="openai",
                family=None,
                color="#10A37F",
                context_window=32_000,
                input_price=None,
                output_price=None,
                released_on=None,
                mode="realtime",
            ),
        ]

    monkeypatch.setattr(overseer_ai_catalog, "list_models", list_models)

    if vendors is None:
        return

    async def catalog_vendors(db: Any) -> list[Any]:
        return vendors

    monkeypatch.setattr(overseer_ai_catalog, "catalog_vendors", catalog_vendors)


@persisted
def test_the_catalog_lists_models_with_prices(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(app, monkeypatch)
    _catalog(monkeypatch)
    rows = select(_get(client, "catalog"), "#ai-catalog tbody tr")
    assert "Claude Haiku 4.5" in text(rows[0]) and "$1.00" in text(rows[0])
    assert "200,000" in text(rows[0])
    assert "gpt-4o-mini" in text(rows[1]) and "openai/gpt" not in text(rows[1])
    assert one(rows[0], "img").get("src") == "/partials/overseer/ai/icons/Anthropic"


@persisted
def test_the_catalog_lists_every_kind_of_model(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A place to look: chat and voice models alike, each saying its kind."""
    seen: list[Any] = []
    client = _client(app, monkeypatch)
    _catalog(monkeypatch, seen)
    rows = select(_get(client, "catalog"), "#ai-catalog tbody tr")
    assert seen[-1]["mode"] is None
    assert "Chat" in text(rows[0]) and "Realtime" in text(rows[2])


@persisted
def test_a_voice_model_is_not_offered_for_chat(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def get_model_info(model_id: str) -> Any:
        return SimpleNamespace(
            model_id=model_id,
            title="GPT Realtime",
            description="",
            vendor="openai",
            context_window=32_000,
            streamable=False,
            enabled=True,
            released_on=None,
            input_price=None,
            output_price=None,
            modalities=["text", "audio"],
            mode="realtime",
        )

    client = _client(app, monkeypatch)
    monkeypatch.setattr(overseer_ai_catalog, "get_model_info", get_model_info)
    drawer = client.get("/partials/overseer/ai/models/drawer?model=gpt-realtime").text
    assert not select(drawer, "form[data-use-model]")
    assert "Realtime" in text(one(drawer, "#ai-model-facts"))


@persisted
def test_the_catalog_searches_and_narrows_to_usable(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    client = _client(app, monkeypatch)
    _catalog(monkeypatch, seen)
    client.get(f"{PAGE}/catalog?q=haiku")
    assert seen[-1]["pattern"] == "haiku" and seen[-1]["vendors"] is None
    client.get(f"{PAGE}/catalog?usable=1")
    assert "anthropic" in seen[-1]["vendors"] and "openai" not in seen[-1]["vendors"]


@persisted
def test_a_model_opens_in_the_drawer_with_use(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def get_model_info(model_id: str) -> Any:
        return SimpleNamespace(
            model_id=model_id,
            title="GPT-4o mini",
            description="Small and fast",
            vendor="openai",
            context_window=128_000,
            streamable=True,
            enabled=True,
            released_on="2024-07-18",
            input_price=0.15,
            output_price=0.6,
            modalities=["text", "image"],
            mode="chat",
        )

    client = _client(app, monkeypatch)
    _catalog(monkeypatch)
    monkeypatch.setattr(overseer_ai_catalog, "get_model_info", get_model_info)
    link = one(select(_get(client, "catalog"), "#ai-catalog tbody tr")[1], "a")
    assert "model=openai%2Fgpt-4o-mini" in link.get("href")
    drawer = client.get("/partials/overseer/ai/models/drawer?model=openai/gpt-4o-mini")
    assert drawer.status_code == 200, drawer.text
    assert "Small and fast" in text(one(drawer.text, "#ai-model-facts"))
    assert one(drawer.text, "form[data-use-model] input[name=model_id]").get(
        "value"
    ) == ("openai/gpt-4o-mini")


@persisted
def test_using_a_model_switches_it(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend.routes.partials import overseer_ai as partials

    switched: list[str] = []

    async def set_active_model(model_id: str, force: bool = False) -> Any:
        switched.append(model_id)
        return SimpleNamespace(success=True, message=f"Switched to {model_id}")

    client = _client(app, monkeypatch)
    monkeypatch.setattr(partials, "set_active_model", set_active_model)
    response = client.post(
        "/partials/overseer/ai/models/use", data={"model_id": "openai/gpt-4o-mini"}
    )
    assert response.status_code == 200 and switched == ["openai/gpt-4o-mini"]
    assert triggers(response)["toast"]["tone"] == "ok"


@persisted
def test_a_refused_switch_is_the_toast(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.components.web_frontend.routes.partials import overseer_ai as partials

    async def set_active_model(model_id: str, force: bool = False) -> Any:
        return SimpleNamespace(success=False, message="Model not in catalog")

    client = _client(app, monkeypatch)
    monkeypatch.setattr(partials, "set_active_model", set_active_model)
    toast = triggers(
        client.post("/partials/overseer/ai/models/use", data={"model_id": "x"})
    )["toast"]
    assert toast["tone"] == "error" and "not in catalog" in toast["text"]


@persisted
def test_the_release_chips_window_the_catalog(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date, timedelta

    seen: list[Any] = []
    client = _client(app, monkeypatch)
    _catalog(monkeypatch, seen)
    client.get(f"{PAGE}/catalog")
    assert seen[-1]["released_after"] is None
    client.get(f"{PAGE}/catalog?released=6m")
    after = seen[-1]["released_after"]
    assert (
        date.today() - timedelta(days=190) < after < date.today() - timedelta(days=170)
    )
    chips = [
        text(a)
        for a in select(
            client.get(f"{PAGE}/catalog").text, "nav[aria-label=Released] a"
        )
    ]
    assert chips == ["3 months", "6 months", "1 year", "All time"]


@persisted
def test_the_catalog_narrows_to_chosen_vendors(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    client = _client(app, monkeypatch)
    _catalog(monkeypatch, seen)
    html = client.get(f"{PAGE}/catalog?vendor=openai&vendor=anthropic").text
    assert sorted(seen[-1]["vendors"]) == ["anthropic", "openai"]
    checked = [i.get("value") for i in select(html, "#ai-vendor-picker input[checked]")]
    assert sorted(checked) == ["anthropic", "openai"]
    chip = select(html, "nav[aria-label=Released] a")[0].get("href")
    assert "vendor=openai" in chip and "vendor=anthropic" in chip


@persisted
def test_usable_and_chosen_vendors_meet(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    client = _client(app, monkeypatch)
    _catalog(monkeypatch, seen)
    client.get(f"{PAGE}/catalog?usable=1&vendor=openai&vendor=anthropic")
    assert seen[-1]["vendors"] == ["anthropic"]  # the only chosen one with a key


@persisted
async def test_the_catalog_reads_its_vendors_on_the_request_session(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    async_client_with_db: TestClient,
    async_db_session: Any,
) -> None:
    """The vendor counts go through the request's own session. Opened on a
    second session after the request's has taken SQLite's write lock (the
    logo lookup takes it), they wait out the busy timeout and fail with
    "database is locked"."""
    from app.services.ai.models.llm.llm_org import LLMOrg

    async_db_session.add(LLMOrg(slug="anthropic", name="Anthropic", icon_b64=PNG_B64))
    await async_db_session.commit()
    _client(app, monkeypatch)
    _catalog(monkeypatch, vendors=None)  # the real vendor read
    labels = [
        text(label)
        for label in select(
            _get(async_client_with_db, "catalog"), "#ai-vendor-picker label"
        )
    ]
    assert any("Anthropic" in label for label in labels)


@persisted
def test_the_vendor_picker_lists_the_catalogs_vendors(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(app, monkeypatch)
    _catalog(monkeypatch)

    async def catalog_vendors(db: Any) -> list[Any]:
        return [
            SimpleNamespace(name="openrouter", model_count=483),
            SimpleNamespace(name="anthropic", model_count=12),
        ]

    monkeypatch.setattr(overseer_ai_catalog, "catalog_vendors", catalog_vendors)
    labels = [
        text(label)
        for label in select(_get(client, "catalog"), "#ai-vendor-picker label")
    ]
    assert "Openrouter" not in labels[0]
    assert "OpenRouter" in labels[0] and "483" in labels[0]
