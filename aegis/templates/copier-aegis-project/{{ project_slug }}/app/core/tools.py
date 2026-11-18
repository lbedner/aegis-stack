"""The tool registry: what a model or an outside assistant may call.

Maps tool names to Python callables and the effect each declares. A grant
decides WHICH tools a caller may use (an agent's ``agent_tool`` rows, an
MCP client's grant); this module decides WHAT each name executes and
whether it may be served at all. It lives in core so any service can
register tools and any surface can serve them, with or without the AI
service. Entries are plain callables; nothing here imports an AI framework.

Services register their own tools at import time:

    from app.core.tools import register_tool

    async def lookup_order(order_id: str) -> OrderSummary:
        \"\"\"Fetch an order summary.\"\"\"
        ...

    register_tool("lookup_order", lookup_order, effect="read")

A tool hands back a model (``FIGURES``), never a dict: its JSON is what
the model reads, and its schema types code mode's script and an MCP
client. A refusal the model can correct from is ``Refused``.
"""

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import copy
from dataclasses import dataclass
import functools
import inspect
from typing import Any, Literal

from pydantic import BaseModel
from pydantic_core import to_json, to_jsonable_python

from app.core.discovery import import_modules_named
from app.core.figures import FIGURES
from app.core.formatting import format_value
from app.core.log import logger

ToolFunc = Callable[..., Any]

# Who a tool call acts for, bound by whatever runs the tool: a chat turn
# (``memory_user``) or the MCP server, per call.
#
# The owner is whose data it reads and whose cards it files: the signed-in
# user, never a name a client sends. ``None`` (a single-tenant install, or
# MCP with no MCP_OWNER_USER_ID) reads every row.
current_owner_user_id: ContextVar[int | None] = ContextVar(
    "current_owner_user_id", default=None
)
# The author of the writes it proposes: which agent asked (an MCP client
# files as ``mcp:<client>``), in which conversation. A write with no
# author cannot be audited, and a card is withdrawable only by its author.
current_agent_slug: ContextVar[str | None] = ContextVar(
    "current_agent_slug", default=None
)
current_conversation_id: ContextVar[str | None] = ContextVar(
    "current_conversation_id", default=None
)
# What the turn is about, beside whose it is: an app's own scope key (a
# project's id, say), decided by the server like the user and bound by
# ``memory_user``. None when the app has no such scope.
current_subject: ContextVar[str | None] = ContextVar("current_subject", default=None)
# Whether it acts for an admin, where its runner knows (MCP: the token's
# admin claim); ``None`` leaves it to the owner (``caller_is_admin`` in
# ``app.services.shared.deps``). An ``admin`` tool answers anyone else so.
current_admin: ContextVar[bool | None] = ContextVar("current_admin", default=None)
ADMIN_ONLY = "Only an admin can use this tool."


@contextmanager
def acting_as(
    owner_user_id: int | None,
    agent_slug: str | None,
    conversation_id: str | None = None,
    admin: bool | None = None,
) -> Iterator[None]:
    """Bind who the tool calls in the block act for, and restore the outer
    binding after. Every field is set, so nothing leaks in from outside:
    an MCP call binds no conversation, whatever a caller had."""
    owner = current_owner_user_id.set(owner_user_id)
    agent = current_agent_slug.set(agent_slug)
    conversation = current_conversation_id.set(conversation_id)
    is_admin = current_admin.set(admin)
    try:
        yield
    finally:
        current_admin.reset(is_admin)
        current_conversation_id.reset(conversation)
        current_agent_slug.reset(agent)
        current_owner_user_id.reset(owner)


# What a call does to the app's state, declared by the tool itself:
# ``read`` changes nothing, ``proposes`` files work for the user's
# approval (nothing lands until they act), ``writes`` changes state at once.
ToolEffect = Literal["read", "proposes", "writes"]

# Effects an outside assistant may reach over MCP. An allowlist, so an
# effect added later is unservable until someone decides otherwise.
_MCP_SERVABLE_EFFECTS: frozenset[str] = frozenset({"read", "proposes"})


@dataclass(frozen=True)
class RegisteredTool:
    """A named tool entry: the callable plus registry metadata.

    Every non-read tool stays a visible native call even in code mode - a
    write or proposal the user has to see in the tool trail is never
    dispatched from inside the sandbox. The tool declares its ``effect`` at
    registration; the agent loader and the MCP server ask the registry
    rather than keeping their own lists.
    """

    name: str
    func: ToolFunc
    description: str | None = None
    effect: ToolEffect = "writes"
    # Shown to admins only, as Overseer shows it: an MCP token reaches it
    # only when its owner is an admin (``mcp.server``).
    admin: bool = False
    # What a call of it is, as a person watching reads it ("Looking up how
    # the parts connect"): ``steps.doing``.
    doing: str | None = None
    # Its result names approval cards (``chat_transcript.card_component``).
    cards: bool = False

    @functools.cached_property
    def served(self) -> ToolFunc:
        """``func`` as every caller is served it (an agent, code mode's
        script, an MCP client): its money in dollars beside its cents
        (``with_dollars``). Its signature and docstring stay ``func``'s,
        so the schema built from it is too; its name is the registered one,
        which an agent calls it by (two modules' ``requests`` would
        collide)."""
        func = self.func
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def served(*args: Any, **kwargs: Any) -> Any:
                return with_dollars(await func(*args, **kwargs))

        else:

            @functools.wraps(func)
            def served(*args: Any, **kwargs: Any) -> Any:
                return with_dollars(func(*args, **kwargs))

        served.__name__ = served.__qualname__ = self.name
        return served


# Code mode's one tool: a script run against the read tools, in the sandbox.
RUN_CODE = "run_code"


class Refused(BaseModel):
    """A call a tool would not carry out, and why: an answer the model
    corrects from, where an exception would end its turn."""

    model_config = FIGURES

    error: str


def result_data(result: Any) -> Any:
    """A tool's result as JSON data: its model dumped, dates and the like as
    their JSON strings, what is already data as it is."""
    return to_jsonable_python(result, fallback=str)


def with_dollars(result: Any) -> Any:
    """``result`` with every ``*_cents`` whole number joined by its dollars
    as ``*_usd`` (``-149203`` -> ``"-$1,492.03"``), all the way down: what a
    model reads of a tool. Tools keep cents (scripts and cards compute with
    them, and a later script reuses the exact figure); a model left to
    convert read an unlabelled 297614 as dollars. A model is read as its
    JSON data; a result with no cents in it comes back as it is, so a model
    without money stays the model its callers type."""
    joined, changed = _joined(result_data(result))
    return joined if changed else result


def _usd_key(key: Any) -> str | None:
    """Where ``with_dollars`` puts a ``*_cents`` key's dollars, or None."""
    if isinstance(key, str) and key.endswith("_cents"):
        return f"{key.removesuffix('_cents')}_usd"
    return None


def _joined(data: Any) -> tuple[Any, bool]:
    """``data`` with its dollars joined, and whether any were: an unchanged
    branch is handed back as it is. A dict already carrying a figure's
    dollars (run_code's result, its reads already joined) keeps them."""
    if isinstance(data, list):
        items = [_joined(item) for item in data]
        if not any(changed for _, changed in items):
            return data, False
        return [item for item, _ in items], True
    if not isinstance(data, dict):
        return data, False
    out: dict[Any, Any] = {}
    changed = False
    for key, item in data.items():
        out[key], inner = _joined(item)
        changed = changed or inner
        usd = _usd_key(key)
        # ``type is int``: a bool is an int, and never money.
        if usd is not None and type(item) is int and usd not in data:
            out[usd] = format_value(item / 100, "money")
            changed = True
    return (out, True) if changed else (data, False)


def with_dollars_schema(schema: dict[str, Any] | None) -> dict[str, Any] | None:
    """A tool's output schema naming the ``*_usd`` string ``with_dollars``
    puts beside each ``*_cents`` property, so a validator holding a closed
    model (``FIGURES`` forbids keys it does not name) admits the dollars."""
    if schema is None:
        return None
    joined = copy.deepcopy(schema)
    _schema_joined(joined)
    return joined


def _schema_joined(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _schema_joined(item)
    if not isinstance(node, dict):
        return
    for item in node.values():
        _schema_joined(item)
    properties = node.get("properties")
    if isinstance(properties, dict):
        for key in list(properties):
            if (usd := _usd_key(key)) is not None and usd not in properties:
                properties[usd] = {"type": "string"}


def result_text(result: Any) -> str:
    """A tool's result as the text a model or a trace reads: a string as
    it is, anything else (a model, above all) as its JSON."""
    if isinstance(result, str):
        return result
    return to_json(result, fallback=str).decode()


_registry: dict[str, RegisteredTool] = {}


def register_tool(
    name: str,
    func: ToolFunc,
    *,
    description: str | None = None,
    effect: ToolEffect | None = None,
    admin: bool = False,
    replace: bool = False,
    doing: str | None = None,
    cards: bool = False,
) -> None:
    """Register a callable under a tool name. ``cards``: its result names
    approval cards, which every chat UI draws (``card_tool_names``).

    A tool that declares no ``effect`` is treated as ``writes``: default-deny,
    so a write that forgets to say so stays a visible native call and never
    reaches an outside assistant. Raises ValueError on a duplicate name
    unless ``replace=True``, and a rebind may not change the effect, so a
    later import can't quietly turn a proposal into a read.
    """
    if effect is None:
        logger.warning(f"Tool {name!r} declares no effect; treated as 'writes'")
        effect = "writes"
    existing = _registry.get(name)
    if existing is not None and not replace:
        raise ValueError(
            f"Tool '{name}' is already registered; pass replace=True to rebind it"
        )
    if existing is not None and existing.effect != effect:
        raise ValueError(
            f"Tool '{name}' is registered as {existing.effect!r}; a rebind "
            f"may not change its effect to {effect!r}"
        )
    _registry[name] = RegisteredTool(
        name=name,
        func=func,
        description=description,
        effect=effect,
        admin=admin,
        doing=doing,
        # A rebind (a plugin, a test double) keeps drawing its cards.
        cards=cards or (existing is not None and existing.cards),
    )


def unregister_tool(name: str) -> None:
    """Remove a registered tool. Raises KeyError if the name is unknown."""
    try:
        del _registry[name]
    except KeyError:
        raise KeyError(f"Tool '{name}' is not registered") from None


def get_tool(name: str) -> RegisteredTool | None:
    """Return the registry entry for a name, or None if unregistered."""
    return _registry.get(name)


def card_tool_names() -> frozenset[str]:
    """Every registered tool whose result names approval cards. A process
    that only draws transcripts (a page, the Flet chat) never built an
    agent, so the registry is loaded here first."""
    _load_once()
    return frozenset(t.name for t in _registry.values() if t.cards)


@functools.cache
def _load_once() -> None:
    load_tools()


def native_write_tool_names() -> frozenset[str]:
    """Every registered tool that must stay native in code mode."""
    return frozenset(t.name for t in _registry.values() if t.effect != "read")


def mcp_servable(
    names: Iterable[str], effects: Iterable[str] = _MCP_SERVABLE_EFFECTS
) -> list[str]:
    """The granted names an MCP client may call: reads and proposals only,
    narrowed to ``effects`` (a token's scope) when given.

    The one gate for MCP. A ``writes`` tool is dropped whatever the grant
    or ``effects`` says, and so is a name with no registered tool. Order is
    preserved.
    """
    allowed = _MCP_SERVABLE_EFFECTS & frozenset(effects)
    return [
        name
        for name in names
        if (tool := _registry.get(name)) is not None and tool.effect in allowed
    ]


def registered_tool_names() -> list[str]:
    """All currently registered tool names, in registration order."""
    return list(_registry)


def load_tools() -> None:
    """Import every service's ``tools`` module, so the registry is whole in
    any process: a chat turn, the MCP server, a seed script. Found on disk
    (``app.core.discovery``), so a service or a plugin registers tools in
    its own ``tools.py`` and nothing else lists it. A module registers at
    import, and importing twice is a no-op."""
    import app.services as services

    import_modules_named(services, "tools")
