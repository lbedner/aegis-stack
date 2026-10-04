"""``Configurable``: annotate a ``Settings`` field with it to list the
setting on the Overseer Settings page, and save it there when the stack has
a writable store (the secrets component).

    DATABASE_BACKUP_KEEP: Annotated[
        int, Configurable("database", "Backups kept; older ones are removed")
    ] = 7

A value is checked against the field's type, and picked from a list where
the type is a closed set (``bool``, a ``Literal``, an ``Enum``) or the marker
names one: ``Configurable("scheduler", "...", choices=timezones)``.

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
    """Who reads the setting, what it is, and the values it may take when
    its type does not say (``choices``). ``owner`` is the component or
    service's key in the one name registry (``database``, ``service_auth``;
    ``get_component_title`` names it): Overseer > Settings groups by it,
    and that component's or service's own page shows its group too."""

    owner: str = "app"
    label: str = ""
    choices: Callable[[], Iterable[str]] | None = None


def timezones() -> list[str]:
    """Every IANA timezone name, for a setting that takes one."""
    return sorted(available_timezones())
