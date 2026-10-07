"""The finance service reads one calendar clock.

``date.today()`` is the host's local date; models, imports, the demo seed
and the scheduler are on UTC. Mixing them made the insight rules flag a
bill as missed that the seed had dated as due today, for the hours each
evening when the two dates differ. ``current_date`` is the only source.
"""

from datetime import UTC, datetime

from pathlib import Path

import pytest

from app.services.finance.utils import current_date
from tests.core.test_time import CLOCK_READS


@pytest.mark.real_clock
def test_current_date_is_the_utc_date() -> None:
    assert current_date() == datetime.now(UTC).date()


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
