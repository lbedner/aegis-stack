"""Each action by name: what can be done with a moment.

An action takes some kinds of moment and runs in one place:

- ``browser`` - nothing to run: the page copies its prompt (Copy for agent)
- ``app`` - its ``run`` is called in the app, at once (Ask Illiana)
- ``runner`` - it waits for a runner on another machine to claim it (Ask
  agent: a coding agent in a fresh worktree, ``meetings runner``)

Registered like tools and detectors. The built-ins are registered here;
another service registers its own in its ``meeting_moments`` module
(``domains.moments.detectors``).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from app.core.discovery import optional
from app.services.meetings.domains.actions.prompt import Excerpt, for_an_agent
from app.services.meetings.domains.moments.detectors import (
    ADDRESSED,
    QUESTION,
    load_extensions,
)

Where = Literal["browser", "app", "runner"]
# What an action that runs in the app does: given its prompt and the owner,
# what it came back with.
AppRun = Callable[[str, int | None], Awaitable[str]]


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    kinds: frozenset[str]
    where: Where
    run: AppRun | None = None
    frame: Callable[[Excerpt], str] = for_an_agent


_actions: dict[str, Action] = {}


def register_action(action: Action, *, replace: bool = False) -> None:
    """Make ``action`` available for its kinds. A name is registered once
    unless ``replace``."""
    if action.name in _actions and not replace:
        raise ValueError(f"An action {action.name!r} is already registered")
    if action.where == "app" and action.run is None:
        raise ValueError(f"Action {action.name!r} runs in the app but has no run")
    _actions[action.name] = action


def action_named(name: str) -> Action | None:
    load_extensions()
    return _actions.get(name)


def actions_for(kind: str) -> list[Action]:
    """The actions a moment of ``kind`` offers, in the order registered."""
    load_extensions()
    return [a for a in _actions.values() if kind in a.kinds]


# Her action (``ask_ai``): she answers, where the stack has her, in a
# conversation of the meetings' own (``SURFACE``, kept out of her chat's list).
ANSWERS = "ai"
SURFACE = "meetings"
# Ask Illiana: rendered only with an AI that runs her.
ASK_ILLIANA = "app.services.meetings.domains.actions.ask_ai"
# What a coding agent can take: a question, asked of the bot by name or not.
QUESTIONS = frozenset({QUESTION, ADDRESSED})

register_action(Action("copy", "Copy for agent", QUESTIONS, "browser"))
register_action(Action("agent", "Ask agent", QUESTIONS, "runner"))

# The stack's model answers too, where it has one.
optional(ASK_ILLIANA)
