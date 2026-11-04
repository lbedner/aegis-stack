"""An agent acting on the page the chat is on (``page_action``): checked
against what the page declares, carried to the page by whatever runs the
turn, and offered only on a page that declares something."""

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest

from app.core.pages import page_stage
from app.core.tools import Refused, result_data
from app.services.ai.domains.chat.agent_loader import default_agent_config
from app.services.ai.domains.chat.page_actions import (
    PAGE_ACTION,
    on_page,
    page_action,
)
from tests._pages import LANDING


@pytest.fixture
def sent() -> Iterator[list[dict[str, Any]]]:
    """A turn on the landing page: what reached the page, in order."""
    reached: list[dict[str, Any]] = []

    async def send(event: dict[str, Any]) -> None:
        reached.append(event)

    with page_stage(LANDING, send):
        yield reached


async def _act(*args: Any) -> Any:
    return result_data(await page_action(*args))


async def test_it_scrolls_to_and_highlights_a_declared_target(
    sent: list[dict[str, Any]],
) -> None:
    assert await _act("scroll", "docs") == {"action": "scroll", "target": "docs"}
    await _act("highlight", "build")
    assert sent == [
        {"action": "scroll", "target": "docs"},
        {"action": "highlight", "target": "build"},
    ]


async def test_a_pages_own_action_carries_its_value_as_checked(
    sent: list[dict[str, Any]],
) -> None:
    await _act("compose", "build", {"components": ["worker"]})
    assert sent == [
        {"action": "compose", "target": "build", "value": {"components": ["worker"]}}
    ]


@pytest.mark.parametrize(
    ("args", "says"),
    [
        (("scroll", "pricing"), "build, docs"),  # the parts it has
        (("compose", "docs"), "scroll, highlight"),  # what that part takes
        (("compose", "build", {"components": "worker"}), "{components: [str, ...]}"),
    ],
)
async def test_what_the_page_does_not_declare_is_refused_never_sent(
    sent: list[dict[str, Any]], args: tuple[Any, ...], says: str
) -> None:
    """Refused to the model, which corrects itself from what it is told."""
    result = await _act(*args)
    assert says in result["error"]
    assert sent == []


async def test_off_a_page_it_does_nothing() -> None:
    result = await page_action("scroll", "docs")
    assert isinstance(result, Refused)


def test_a_turn_on_a_declared_page_is_offered_the_tool_and_told_the_page(
    sent: list[dict[str, Any]],
) -> None:
    config = default_agent_config()
    offered = on_page(config)
    assert offered.tool_names == (*config.tool_names, PAGE_ACTION)
    assert offered.system_prompt.startswith(config.system_prompt)
    told = offered.system_prompt.removeprefix(config.system_prompt)
    assert "scroll or highlight" in told
    assert "- build: Compose a stack" in told and "- docs: Where the docs start" in told
    assert "compose" in told and "{components: [str, ...]}" in told


def test_off_a_page_there_is_no_tool_whatever_the_row_grants() -> None:
    config = default_agent_config()
    assert on_page(config) == config  # nothing to take away, no word of one
    granted = replace(config, tool_names=(*config.tool_names, PAGE_ACTION))
    assert on_page(granted).tool_names == config.tool_names
