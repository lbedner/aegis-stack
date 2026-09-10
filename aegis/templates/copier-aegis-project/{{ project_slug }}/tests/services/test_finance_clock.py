"""The finance service reads one calendar clock.

``date.today()`` is the host's local date; models, imports, the demo seed
and the scheduler are on UTC. Mixing them made the insight rules flag a
bill as missed that the seed had dated as due today, for the hours each
evening when the two dates differ. ``current_date`` is the only source.
"""

from datetime import UTC, datetime
from pathlib import Path

from importlib import import_module
from importlib.util import find_spec

from app.services import finance
from app.services.finance.utils import current_date


def test_current_date_is_the_utc_date() -> None:
    assert current_date() == datetime.now(UTC).date()


# The service, its API, and (when the htmx component is present) the web
# routes that render it.
ROOTS = [Path(finance.__file__).parent] + [
    Path(import_module(name).__file__ or "").parent
    for name in ("app.components.backend.api.finance", "app.components.web_frontend")
    if find_spec(name) is not None
]


def test_no_local_clock_in_finance_code() -> None:
    """The service, its API, and the web routes that render it."""
    offenders = [
        str(p)
        for root in ROOTS
        for p in root.rglob("*.py")
        if "date.today()" in p.read_text() or "datetime.now().date()" in p.read_text()
    ]
    assert offenders == [], f"local-clock reads (use utils.current_date): {offenders}"
