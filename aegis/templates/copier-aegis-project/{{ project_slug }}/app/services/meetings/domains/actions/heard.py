"""The parts of the system a line of a call names: by the names each is
said by, strict, so talk that only uses a part's ordinary word ("worker",
"finance") stays plain.

A part is heard by its full name (the ``finance service``, the ``cache
component``), an outside provider by its own (``Plaid``), the worker and
the database by the tool this stack runs them on (``arq``, ``Postgres``),
and some parts by what people call them (``ALSO_HEARD``: ``Redis``, ``the
scheduler``). Only the parts this stack has are heard; a chip says the
name as it was heard, not Overseer's title for the part. No model reads
the talk: a name is a whole word, matched in any case (``app.core.terms``).
"""

from collections.abc import Iterable
from dataclasses import dataclass
import re

from app.core.ontology.model import Kind, Node, SystemModel
from app.core.terms import term_key, terms_pattern

# What people call a part, beyond its full name: its own tool's name where
# that is what is said (Redis for the cache), or "the" and its word where
# the word alone is too ordinary to be it. Each part's name once, as said.
ALSO_HEARD: dict[str, tuple[str, ...]] = {
    "component:backend": ("the backend", "FastAPI"),
    "component:browser": ("Chromium", "Playwright"),
    "component:cache": ("Redis", "the cache"),
    "component:database": ("the database",),
    "component:deploy": ("the deploy agent",),
    "component:frontend": ("Flet",),
    "component:observability": ("Logfire",),
    "component:ollama": ("Ollama",),
    "component:queue": ("the queue",),
    "component:scheduler": ("the scheduler",),
    "component:storage": ("SeaweedFS",),
    "component:web_frontend": ("htmx",),
    "component:worker": ("the worker", "the workers"),
    "service:meetings.bot": ("the meeting bot",),
    "shared:change_queue": ("the change queue",),
}
# The option naming the tool a part runs on, said for the part as this stack
# chose it (``PartOption.chosen``): "arq" is the worker on an arq stack.
RUNS_ON = {"component:worker": "backend", "component:database": "engine"}


def said_names(node: Node) -> tuple[str, ...]:
    """The names ``node`` is said by: a part's full name (a service or a
    component, by its word), a provider's own, the tool it runs on, and what
    people call it."""
    word = node.name.replace("_", " ")
    own: tuple[str, ...] = ()
    if node.kind is Kind.EXTERNAL:
        own = (node.name,)
    elif node.kind in (Kind.SERVICE, Kind.COMPONENT) and "." not in node.name:
        own = (f"{word} {node.kind.value}",)
    tool = RUNS_ON.get(node.id)
    chosen = [
        o.chosen
        for o in getattr(node, "options", ())
        if o.name == tool and isinstance(o.chosen, str)
    ]
    return own + tuple(chosen) + ALSO_HEARD.get(node.id, ())


@dataclass(frozen=True)
class Heard:
    """The parts a stack's talk can name, by every name each is said by."""

    parts: dict[str, tuple[str, str]]  # a name (``term_key``): its part, heading
    pattern: re.Pattern[str]

    @property
    def ids(self) -> frozenset[str]:
        """The parts talk can name, by id."""
        return frozenset(part for part, _ in self.parts.values())

    def named(self, text: str) -> list[tuple[str, str]]:
        """The parts ``text`` names, first named first, each once: its id and
        the name it was heard by, as a heading says it ("Scheduler")."""
        found: dict[str, str] = {}
        for match in self.pattern.finditer(text):
            if known := self.parts.get(term_key(match.group())):
                found.setdefault(*known)
        return list(found.items())


def heard(nodes: Iterable[Node]) -> Heard:
    """What talk can name among ``nodes``: every part and provider, by the
    names it is said by (``said_names``)."""
    parts = {
        term_key(name): (n.id, _heading(name)) for n in nodes for name in said_names(n)
    }
    return Heard(parts, terms_pattern(parts))


_kept: tuple[SystemModel, Heard] | None = None


def heard_here() -> Heard:
    """What talk can name in this stack (``heard`` over the twin's
    ``current`` model), made once a model. The twin's first build parses the
    source: an async caller asks off the loop (``asyncio.to_thread``)."""
    global _kept
    from app.core.ontology.system import current  # the twin, built when asked

    model = current()
    if _kept is None or _kept[0] is not model:
        _kept = (model, heard(model.nodes))
    return _kept[1]


def _heading(name: str) -> str:
    """A name as a heading says it: "the scheduler" is "Scheduler"."""
    bare = name.removeprefix("the ")
    return bare[:1].upper() + bare[1:]
