"""One cadence table, and every view derived from it.

A cadence carries six independent facts: what it is called, how to step a
date by it, what gap detection should match, its monthly-equivalent
weight, how late is late, and whether it may be stored. Those lived in
six hand-written maps in five modules, and they drifted:

- the forecast could step ``semi_annually`` and ``bimonthly`` long before
  detection could name them, so a six-month insurance premium measured as
  "irregular" and vanished from the projection;
- the menus were extended to offer both, but the create/update validator
  was not, so the dropdown produced a 422;
- and the API schema still listed six, so the fix at the service layer
  never reached the endpoint.

Each of those was found by a different bug report. The point of the table
is that the next cadence is added once.
"""

from app.services.finance.constants import CADENCE_KEYS, CADENCES


class TestTheTableIsComplete:
    def test_every_cadence_carries_every_fact(self) -> None:
        for key, cadence in CADENCES.items():
            assert cadence.label, key
            assert cadence.detect_days > 0, key
            assert cadence.monthly_factor > 0, key
            assert cadence.grace_days > 0, key
            assert (cadence.months or 0) or (cadence.days or 0), key

    def test_the_keys_are_ordered_shortest_first(self) -> None:
        """``_frequency_for`` returns the FIRST band a median falls in, so
        the order is load-bearing: where two bands touch, the shorter
        cadence takes the overlap."""
        spans = [c.detect_days for c in CADENCES.values()]
        assert spans == sorted(spans)

    def test_a_monthly_factor_matches_its_own_step(self) -> None:
        """The rollup weight and the step are two descriptions of the same
        interval; letting them disagree is how a bill is counted at the
        wrong size in the monthly headline."""
        for key, c in CADENCES.items():
            implied = 30.44 / c.detect_days
            assert abs(c.monthly_factor - implied) < 0.12, (
                f"{key}: factor {c.monthly_factor:.3f} vs {implied:.3f} implied"
            )


class TestEveryViewIsDerived:
    def test_the_forecast_steps_exactly_these(self) -> None:
        """Steps stay cadence-only: ``once`` projects a single occurrence
        by its own rule and must never be stepped."""
        from app.services.finance.utils import FREQUENCY_STEPS

        assert set(FREQUENCY_STEPS) == set(CADENCE_KEYS)

    def test_the_validator_accepts_cadences_plus_once(self) -> None:
        from app.services.finance.constants import ONE_TIME_FREQUENCY
        from app.services.finance.service import FinanceService

        assert set(FinanceService._STREAM_FREQUENCIES) == (
            set(CADENCE_KEYS) | {ONE_TIME_FREQUENCY}
        )

    def test_the_bill_menus_offer_cadences_plus_once(self) -> None:
        """The dropdowns for a bill you STATE (Add, edit) offer "One
        time"; the cadence table itself stays pure so detection and the
        forecast never see it."""
        from app.components.frontend.dashboard.modals.finance_modal import (
            _FREQUENCY_LABELS,
            BILL_FREQUENCY_OPTIONS,
        )
        from app.services.finance.constants import ONE_TIME_FREQUENCY

        assert set(_FREQUENCY_LABELS) == set(CADENCE_KEYS)
        assert set(BILL_FREQUENCY_OPTIONS) == set(CADENCE_KEYS) | {ONE_TIME_FREQUENCY}

    def test_the_rollup_weights_exactly_these(self) -> None:
        from app.services.finance.domains.detection.insights import MONTHLY_FACTOR

        assert set(MONTHLY_FACTOR) == set(CADENCE_KEYS)

    def test_detection_matches_a_subset(self) -> None:
        """Detection may know fewer - a cadence can be user-stated only.
        The reverse is the bug: measuring something nothing can step."""
        from app.services.finance.domains.detection.recurring.cadence import _CADENCES

        assert {label for _days, label in _CADENCES} <= set(CADENCE_KEYS)

    def test_the_api_schema_accepts_exactly_these(self) -> None:
        """The layer the earlier fixes never reached: a service that
        stores semiannual behind a schema that rejects it is a 422 the
        user reads as "the app will not let me say what this bill is"."""
        from app.services.finance.constants import ONE_TIME_FREQUENCY
        from app.services.finance.schemas import (
            RecurringStreamCreate,
            RecurringStreamUpdate,
        )

        for model in (RecurringStreamCreate, RecurringStreamUpdate):
            allowed = _literal_values(model, "frequency")
            assert allowed == set(CADENCE_KEYS) | {ONE_TIME_FREQUENCY}, model.__name__


def _literal_values(model: type, field: str) -> set[str]:
    """The Literal options a pydantic field accepts, optional or not."""
    import typing

    annotation = model.model_fields[field].annotation
    found: set[str] = set()

    def walk(node: object) -> None:
        if typing.get_origin(node) is typing.Literal:
            found.update(typing.get_args(node))
            return
        for arg in typing.get_args(node):
            walk(arg)

    walk(annotation)
    return found


class TestTheStepIsRight:
    def test_calendar_months_land_on_the_same_day(self) -> None:
        from datetime import date

        from app.services.finance.constants import step_cadence

        assert step_cadence("monthly", date(2026, 1, 31)) == date(2026, 2, 28)
        assert step_cadence("quarterly", date(2026, 1, 15)) == date(2026, 4, 15)
        assert step_cadence("semi_annually", date(2026, 2, 25)) == date(2026, 8, 25)
        assert step_cadence("annually", date(2026, 3, 1)) == date(2027, 3, 1)

    def test_day_based_cadences_step_by_days(self) -> None:
        from datetime import date

        from app.services.finance.constants import step_cadence

        assert step_cadence("weekly", date(2026, 1, 1)) == date(2026, 1, 8)
        assert step_cadence("biweekly", date(2026, 1, 1)) == date(2026, 1, 15)
