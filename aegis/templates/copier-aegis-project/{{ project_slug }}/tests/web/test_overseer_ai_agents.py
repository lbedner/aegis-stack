"""The Overseer AI page's Agents and Memory sections: the agent registry
(each agent's definition, edited in the drawer), memory modules (edited,
with a preview of what they render), and the facts saved about a user
(corrected and forgotten). Every write goes through the registry's own
functions on the request's session."""

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip(
    "app.services.ai.domains.chat.agent_registry",
    reason="agents and memory need an AI persistence backend",
)

from app.components.web_frontend import overseer_ai_agents  # noqa: E402
from app.components.web_frontend.routes.partials import (  # noqa: E402
    overseer_ai as partials,
)
from app.services.system.models import ComponentStatus  # noqa: E402
from tests.web.dom import one, select, text, triggers  # noqa: E402
from tests.web.overseer import sign_in, status_with  # noqa: E402

PAGE = "/overseer/services/ai"
PARTIALS = "/partials/overseer/ai"
AGENT: dict[str, Any] = {
    "slug": "illiana",
    "name": "Illiana",
    "description": "The finance analyst",
    "category": "finance",
    "model_id": "claude-haiku-4-5-20251001",
    "temperature": 0.3,
    "max_tokens": 2000,
    "system_prompt": "You are careful with money.",
    "is_active": True,
    "code_mode": False,
    "tools": ["save_memory", "search_transactions"],
    "memory_modules": ["user_facts"],
    "knowledge_base_ids": [],
}


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def agents(db: Any) -> list[dict[str, Any]]:
        return [
            AGENT,
            AGENT
            | {
                "slug": "helper",
                "name": "Helper",
                "model_id": None,
                "is_active": False,
                "tools": [],
            },
        ]

    monkeypatch.setattr(overseer_ai_agents, "agent_rows", agents)
    ai = ComponentStatus(name="ai", message="AI", metadata={"engine": "pydantic-ai"})
    sign_in(app, monkeypatch, status_with(services=[ai]))
    return TestClient(app)


def _get(client: TestClient, section: str, query: str = "") -> str:
    response = client.get(f"{PAGE}/{section}" + (f"?{query}" if query else ""))
    assert response.status_code == 200, response.text
    return response.text


def test_agents_list_each_definition(client: TestClient) -> None:
    rows = select(_get(client, "agents"), "#ai-agents tbody tr")
    first = text(rows[0])
    assert "Illiana" in first and "finance" in first and "claude-haiku" in first
    assert "Active" in first
    assert "Default" in text(rows[1]) and "Off" in text(rows[1])


def test_an_agent_opens_in_the_drawer(client: TestClient) -> None:
    link = one(select(_get(client, "agents"), "#ai-agents tbody tr")[0], "a")
    assert "agent=illiana" in link.get("href")
    sync = one(_get(client, "agents", "agent=illiana"), "[data-drawer-sync]")
    assert sync.get("data-drawer-url") == f"{PARTIALS}/agents/illiana/drawer"


def test_the_drawer_edits_the_definition(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def one_agent(db: Any, slug: str) -> dict[str, Any] | None:
        return AGENT if slug == "illiana" else None

    monkeypatch.setattr(overseer_ai_agents, "agent_row", one_agent)
    html = client.get(f"{PARTIALS}/agents/illiana/drawer").text
    form = one(html, "form[data-agent]")
    assert one(form, "input[name=name]").get("value") == "Illiana"
    assert "careful with money" in text(one(form, "textarea[name=system_prompt]"))
    assert one(form, "input[name=is_active]").get("checked") is not None
    assert "search_transactions" in text(one(html, "#ai-agent-grants"))
    assert client.get(f"{PARTIALS}/agents/nobody/drawer").status_code == 404


CATALOG = [
    {
        "model_id": "claude-haiku-4-5-20251001",
        "title": "Anthropic: Claude Haiku 4.5",
        "vendor": "Anthropic",
    },
    {"model_id": "qwen3:4b", "title": "qwen3:4b", "vendor": "Ollama"},
]


@pytest.mark.parametrize(
    ("model_id", "listed"),
    [("claude-haiku-4-5-20251001", True), ("retired-model-1", False), (None, True)],
)
def test_the_model_is_picked_from_the_models_this_install_can_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    model_id: str | None,
    listed: bool,
) -> None:
    """Grouped by vendor, blank for the active model; a model the catalog no
    longer lists stays chosen, so saving does not quietly drop it."""
    from app.components.web_frontend import chat_models

    async def one_agent(db: Any, slug: str) -> dict[str, Any] | None:
        return AGENT | {"model_id": model_id}

    async def catalog(mode: str = "chat") -> list[dict[str, Any]]:
        return CATALOG

    monkeypatch.setattr(overseer_ai_agents, "agent_row", one_agent)
    monkeypatch.setattr(chat_models, "catalog", catalog)
    form = one(client.get(f"{PARTIALS}/agents/illiana/drawer").text, "form[data-agent]")
    picker = one(form, "select[name=model_id]")
    assert text(select(picker, "option")[0]) == "The active model"
    groups = [g.get("label") for g in select(picker, "optgroup")]
    assert {"Anthropic", "Ollama"} <= set(groups)
    chosen = one(picker, "option[selected]")
    assert chosen.get("value") == (model_id or "")
    if not listed:
        assert "retired-model-1" in text(chosen)


async def test_the_model_list_is_read_after_the_agent_is(
    async_db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catalog reads on its own connection: with the agent's read still
    open on the request's, SQLite makes it wait out the busy timeout behind
    its own request, and the drawer hangs, then comes up empty."""
    from sqlmodel import text as sql

    from app.components.web_frontend import chat_models

    async def read_agent(db: Any, slug: str) -> dict[str, Any] | None:
        await db.exec(sql("SELECT 1"))
        return AGENT

    open_at_catalog: list[bool] = []

    async def catalog(mode: str = "chat") -> list[dict[str, Any]]:
        open_at_catalog.append(async_db_session.in_transaction())
        return CATALOG

    monkeypatch.setattr(overseer_ai_agents, "agent_row", read_agent)
    monkeypatch.setattr(chat_models, "catalog", catalog)
    assert await overseer_ai_agents.agent_context(async_db_session, "illiana")
    assert open_at_catalog == [False]


def test_saving_an_agent_sends_only_its_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    async def update(db: Any, slug: str, changes: dict[str, Any]) -> Any:
        sent.append((slug, changes))
        return SimpleNamespace(name=changes.get("name", slug))

    monkeypatch.setattr(partials, "update_agent", update)
    response = client.post(
        f"{PARTIALS}/agents/illiana",
        data={
            "name": "Illiana",
            "description": "",
            "category": "finance",
            "model_id": "",
            "temperature": "0.5",
            "max_tokens": "",
            "system_prompt": "Be brief.",
        },
    )
    assert response.status_code == 200, response.text
    slug, changes = sent[0]
    assert slug == "illiana" and changes["temperature"] == 0.5
    assert changes["model_id"] is None and changes["max_tokens"] is None
    assert changes["is_active"] is False  # an unticked box is off
    assert triggers(response)["toast"]["tone"] == "ok"


def test_saving_from_the_chat_stays_in_the_chat(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opened from a reply, Save keeps the drawer and the thread where they
    are, instead of navigating to the Agents page."""

    async def update(db: Any, slug: str, changes: dict[str, Any]) -> Any:
        return SimpleNamespace(name="Illiana")

    monkeypatch.setattr(partials, "update_agent", update)
    response = client.post(
        f"{PARTIALS}/agents/illiana", data={"name": "Illiana", "stay": "1"}
    )
    assert response.status_code == 200
    assert "HX-Location" not in response.headers
    assert "dialog:close" not in response.headers.get("HX-Trigger-After-Settle", "")
    assert "Saved Illiana" in triggers(response)["toast"]["text"]


def test_a_refused_agent_change_is_the_toast(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.ai.domains.chat.agent_registry import InvalidAgentUpdateError

    async def update(db: Any, slug: str, changes: dict[str, Any]) -> Any:
        raise InvalidAgentUpdateError("temperature must be between 0 and 2")

    monkeypatch.setattr(partials, "update_agent", update)
    response = client.post(
        f"{PARTIALS}/agents/illiana", data={"name": "Illiana", "temperature": "9"}
    )
    toast = triggers(response)["toast"]
    assert toast["tone"] == "error" and "between 0 and 2" in toast["text"]


def test_a_bad_number_is_refused_before_the_registry(client: TestClient) -> None:
    response = client.post(
        f"{PARTIALS}/agents/illiana", data={"name": "Illiana", "temperature": "warm"}
    )
    assert triggers(response)["toast"]["tone"] == "error"


MODULE: dict[str, Any] = {
    "slug": "user_facts",
    "name": "User facts",
    "description": "What the user told it",
    "category": "memory",
    "prompt_content": None,
    "fetch_function": "fetch_user_facts",
    "context_key": "facts",
    "supports_days_back": False,
    "default_days_back": None,
    "priority": 10,
    "token_estimate": 200,
    "is_active": True,
}
FACTS = [
    {
        "index": 0,
        "category": "money",
        "fact": "Rent is $2,100",
        "saved_at": "2026-09-01T10:00:00+00:00",
    },
    {
        "index": 1,
        "category": "general",
        "fact": "Prefers short answers",
        "saved_at": "2026-09-02T10:00:00+00:00",
    },
]


@pytest.fixture
def memory(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def modules(db: Any) -> list[dict[str, Any]]:
        return [
            MODULE,
            MODULE
            | {
                "slug": "persona",
                "name": "Persona",
                "fetch_function": None,
                "prompt_content": "Be kind.",
                "is_active": False,
            },
        ]

    async def facts(db: Any) -> list[dict[str, Any]]:
        return FACTS

    monkeypatch.setattr(overseer_ai_agents, "module_rows", modules)
    monkeypatch.setattr(overseer_ai_agents, "fact_rows", facts)
    return client


def test_memory_lists_modules_and_saved_facts(memory: TestClient) -> None:
    html = _get(memory, "memory")
    modules = select(html, "#ai-modules tbody tr")
    assert "User facts" in text(modules[0]) and "fetch_user_facts" in text(modules[0])
    assert "Static text" in text(modules[1])
    facts = [text(r) for r in select(html, "#ai-facts tbody tr:not([data-detail])")]
    assert "Rent is $2,100" in facts[0] and "money" in facts[0]


def test_a_module_opens_with_its_preview(
    memory: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def one_module(db: Any, slug: str) -> dict[str, Any] | None:
        return MODULE if slug == "user_facts" else None

    async def preview(db: Any, slug: str) -> str | None:
        return "Rent is $2,100"

    monkeypatch.setattr(overseer_ai_agents, "module_row", one_module)
    monkeypatch.setattr(overseer_ai_agents, "render_preview", preview)
    link = one(select(_get(memory, "memory"), "#ai-modules tbody tr")[0], "a")
    assert "module=user_facts" in link.get("href")
    html = memory.get(f"{PARTIALS}/modules/user_facts/drawer").text
    assert "Rent is $2,100" in text(one(html, "#ai-module-preview"))
    assert one(html, "form[data-module] input[name=priority]").get("value") == "10"
    assert memory.get(f"{PARTIALS}/modules/nobody/drawer").status_code == 404


def test_saving_a_module_sends_its_fields(
    memory: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    async def update(db: Any, slug: str, changes: dict[str, Any]) -> Any:
        sent.append((slug, changes))
        return SimpleNamespace(name="User facts")

    monkeypatch.setattr(partials, "update_module", update)
    response = memory.post(
        f"{PARTIALS}/modules/user_facts",
        data={
            "name": "User facts",
            "priority": "5",
            "token_estimate": "",
            "is_active": "on",
        },
    )
    assert response.status_code == 200, response.text
    slug, changes = sent[0]
    assert changes["priority"] == 5 and changes["token_estimate"] is None
    assert changes["is_active"] is True and "prompt_content" not in changes


def test_a_fact_is_corrected(
    memory: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[int, str, str]] = []

    async def correct(db: Any, index: int, fact: str, category: str) -> Any:
        sent.append((index, fact, category))
        return {}

    monkeypatch.setattr(partials, "correct_fact", correct)
    form = memory.get(f"{PARTIALS}/facts/0/edit").text
    assert one(form, "textarea[name=fact]") is not None
    response = memory.post(
        f"{PARTIALS}/facts/0", data={"fact": "Rent is $2,200", "category": "money"}
    )
    assert sent == [(0, "Rent is $2,200", "money")]
    assert triggers(response)["toast"]["tone"] == "ok"


def test_a_fact_is_forgotten(
    memory: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    forgot: list[int] = []

    async def forget(db: Any, index: int) -> Any:
        forgot.append(index)
        return {}

    monkeypatch.setattr(partials, "forget_fact", forget)
    assert select(
        memory.get(f"{PARTIALS}/facts/1/confirm-forget").text, "button[hx-delete]"
    )
    assert memory.delete(f"{PARTIALS}/facts/1").status_code == 204
    assert forgot == [1]
