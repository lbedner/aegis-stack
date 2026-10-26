"""How an agent's data is modelled: a field that is not one, or a figure
changed after it was read, is refused. Every model an agent, the API or
Overseer reads takes ``model_config = FIGURES``."""

from pydantic import ConfigDict

FIGURES = ConfigDict(frozen=True, extra="forbid")
