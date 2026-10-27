"""How an agent's data is modelled: a field that is not one, or a figure
changed after it was read, is refused. Every model an agent, the API or
Overseer reads takes ``model_config = FIGURES``."""

from typing import Any

from pydantic import ConfigDict, Field

FIGURES = ConfigDict(frozen=True, extra="forbid")


def absent() -> Any:
    """A field an answer leaves out when it does not apply (None), rather
    than hand the reader a null: ``url: str | None = absent()``. The schema
    still names it."""
    return Field(default=None, exclude_if=lambda value: value is None)
