"""What an agent is doing, step by step, for whoever is watching (a meeting
bot's card): each tool call a turn makes is heard (``heard``) where it runs
(the AI service's ``resolve_tools``, so a read inside a code-mode script is
one too; a script itself where the model asks for it) by the listener bound
where the turn runs (``watching``, an ``app.core.hooks.Hook``), as a phrase
a person reads (``doing``), then the call itself (its name and arguments),
for a listener that shows more than the phrase (a chat's trail)."""

from typing import Any

from app.core.hooks import Hook
from app.core.tools import RUN_CODE, get_tool

# A script with no first comment.
SCRIPT = "Running a script"
# The model thinking before it answers or calls: for a local model, minutes
# nothing else shows.
THINKING = "Thinking"

_steps = Hook("step")
watching = _steps.watching


def heard(name: str, detail: Any = "") -> None:
    """A tool call starting (``name``, its arguments or script as
    ``detail``), to whoever is watching, as ``doing`` says it."""
    if _steps.listened:
        text = detail if isinstance(detail, str) else ""
        _steps.tell(doing(name, text), name, detail)


def doing(name: str, detail: str = "") -> str:
    """A tool call as a person reads it: what the tool says it is doing
    (``register_tool(doing=)``), a script's first comment, else the tool's
    name made readable."""
    tool = get_tool(name)
    if tool is not None and tool.doing:
        return tool.doing
    if name == RUN_CODE:
        first = (detail.strip().splitlines() or [""])[0]
        return first.lstrip("#").strip() if first.startswith("#") else SCRIPT
    return name.replace("_", " ").capitalize()
