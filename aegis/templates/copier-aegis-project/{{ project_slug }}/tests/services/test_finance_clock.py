"""The finance service reads one calendar clock.

``date.today()`` is the host's local date; models, imports, the demo seed
and the scheduler are on UTC. Mixing them made the insight rules flag a
bill as missed that the seed had dated as due today, for the hours each
evening when the two dates differ. ``current_date`` is the only source.
"""

from datetime import UTC, datetime

import pytest
from pathlib import Path

from importlib import import_module
from importlib.util import find_spec

from app.services import finance
from app.services.finance.utils import current_date


@pytest.mark.real_clock
def test_current_date_is_the_utc_date() -> None:
    assert current_date() == datetime.now(UTC).date()


# The service, its API, and (when the htmx component is present) the web
# routes that render it.
ROOTS = [Path(finance.__file__).parent] + [
    Path(import_module(name).__file__ or "").parent
    for name in ("app.components.backend.api.finance", "app.components.web_frontend")
    if find_spec(name) is not None
]


# Calendar reads that bypass ``current_date``: the host's local date, and
# the UTC ones that were written out by hand instead of asking the service.
CLOCK_READS = (
    "date.today()",
    "datetime.now().date()",
    "datetime.now(UTC).date()",
    "utcnow().date()",
)
CLOCK = Path(finance.__file__).parent / "utils.py"


def test_no_local_clock_in_finance_code() -> None:
    """The service, its API, and the web routes that render it read the
    calendar through ``current_date`` only - including the provider syncs,
    whose own ``utcnow().date()`` once meant a test could not pin them."""
    offenders = [
        str(p)
        for root in ROOTS
        for p in root.rglob("*.py")
        if p != CLOCK and any(read in p.read_text() for read in CLOCK_READS)
    ]
    assert offenders == [], f"calendar reads (use utils.current_date): {offenders}"


def test_finance_tests_date_things_by_the_finance_calendar() -> None:
    """A test that drives finance code seeds and checks dates by
    ``current_date`` (pinned by the conftest), never the real clock: the
    real one drifts away from whatever the service was told today is."""
    tests_root = Path(__file__).resolve().parents[1]
    offenders = [
        str(p.relative_to(tests_root))
        for p in tests_root.rglob("test_*.py")
        if p.resolve() != Path(__file__).resolve()
        and "app.services.finance" in (text := p.read_text())
        and any(
            read in line
            for line in text.splitlines()
            if not line.lstrip().startswith("#")
            for read in CLOCK_READS
        )
    ]
    assert offenders == [], f"real-clock dates in finance tests: {offenders}"
