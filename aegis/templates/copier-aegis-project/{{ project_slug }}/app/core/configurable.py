"""``Configurable``: annotate a ``Settings`` field with it to list the
setting on the Overseer Settings page, and save it there when the stack has
a writable store (the secrets component).

    MEMORY_THRESHOLD_PERCENT: Annotated[
        float, Configurable("Health", "Memory warning level, percent")
    ] = 90.0

A value is checked against the field's type, and picked from a list where
the type is a closed set (``bool``, a ``Literal``, an ``Enum``) or the marker
names one: ``Configurable("Scheduler", choices=timezones)``.

A saved value is loaded into ``settings`` as each process starts
(``app.core.saved_settings``), so it takes effect on the next restart, and
only for code that reads ``settings`` when it runs: a value copied at
import (a class attribute, a module constant) never sees it, so leave
those unmarked. Never mark what the app needs before the database is
reachable (``DATABASE_URL``, ``REDIS_URL``, ``SECRET_KEY``,
``ENCRYPTION_KEY``). Its own module so ``config`` can use it without
importing ``secrets``, which imports ``config``.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from zoneinfo import available_timezones


@dataclass(frozen=True)
class Configurable:
    """Who reads the setting (the page groups by it), what it is, and the
    values it may take when its type does not say (``choices``)."""

    owner: str = "App"
    label: str = ""
    choices: Callable[[], Iterable[str]] | None = None


def timezones() -> list[str]:
    """Every IANA timezone name, for a setting that takes one."""
    return sorted(available_timezones())
