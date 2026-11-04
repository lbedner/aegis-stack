"""The agent's hand on the page the chat is on (``app.core.pages``).

A turn on a declared page is offered ``page_action`` and told the page's
parts (``on_page``, where every turn's agent is built); the tool checks
an action against the page and sends it there. Off a declared page there
is no tool and no word of one, whatever an agent's row grants.
"""

from dataclasses import replace
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.figures import FIGURES, misfit, shape_of
from app.core.log import logger
from app.core.pages import BUILT_IN, Page, staged_page
from app.core.tools import Refused, register_tool
from app.services.ai.domains.chat.agent_loader import AgentConfig
from app.services.ai.domains.chat.prompts import meant

PAGE_ACTION = "page_action"


class Acted(BaseModel):
    """An action sent to the page."""

    model_config = FIGURES

    action: str
    target: str


def _refused(error: str) -> Refused:
    logger.warning("A page action was refused", error=error)
    return Refused(error=error)


async def page_action(
    action: str, target: str, value: dict[str, Any] | None = None
) -> Acted | Refused:
    """Act on the page they are on: scroll to one of its parts, highlight
    it (scrolling there too), or one of its own actions with its value.
    Its parts, by id, and what each takes are in your prompt (The page
    they are on). Point at a part as you start to talk about it.

    Answers the 'action' and 'target' sent, or an 'error' saying what to
    fix: nothing reached the page."""
    staged = staged_page()
    if staged is None:
        return Refused(error="They are on no page you can act on.")
    page, send = staged
    found = page.get(target)
    if found is None:
        parts = ", ".join(t.id for t in page.targets)
        return _refused(f"The page has no part {target!r}. Its parts: {parts}.")
    event: dict[str, Any] = {"action": action, "target": target}
    if action not in BUILT_IN:
        own = found.action(action)
        if own is None:
            takes = ", ".join([*BUILT_IN, *(a.name for a in found.actions)])
            return _refused(f"{target} takes no {action!r}. It takes: {takes}.")
        try:
            checked = own.value.model_validate(value or {})
        except ValidationError as exc:
            return _refused(f"{action} on {target}: {misfit(exc, own.value)}")
        event["value"] = checked.model_dump(mode="json")
    await send(event)
    return Acted(action=action, target=target)


def page_brief(page: Page) -> str:
    """The page, as the agent is told it: each part by id and what it is,
    and the actions of the page's own each takes, with their values."""
    lines = [
        "## The page they are on",
        f"{PAGE_ACTION} can {' or '.join(BUILT_IN)} these parts, by id:",
    ]
    for target in page.targets:
        lines.append(f"- {target.id}: {target.about}")
        lines.extend(
            f"  - also {a.name}: {a.about}. Its value: {shape_of(a.value)}"
            for a in target.actions
        )
    return "\n".join(lines)


def on_page(config: AgentConfig) -> AgentConfig:
    """``config`` for a turn on the page it is on (``page_stage``): offered
    the page tool and told the page. Off one, the tool is taken away, so
    a row that grants it holds nothing that answers only a page."""
    others = tuple(name for name in config.tool_names if name != PAGE_ACTION)
    staged = staged_page()
    if staged is None:
        return config if others == config.tool_names else replace(
            config, tool_names=others
        )
    return replace(
        config,
        tool_names=(*others, PAGE_ACTION),
        # After what the row means: a legacy row still gets the default.
        system_prompt=f"{meant(config.system_prompt)}\n\n{page_brief(staged[0])}",
    )


register_tool(
    PAGE_ACTION,
    page_action,
    description="Scroll to, highlight or act on a part of the page they are on",
    # It changes what they see, not what the app holds.
    effect="read",
    replace=True,
    doing="Pointing it out",
)
