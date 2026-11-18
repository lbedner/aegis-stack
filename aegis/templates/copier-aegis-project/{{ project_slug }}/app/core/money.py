"""Money as a chart draws it: minor units to dollars, for the htmx
filters and the Flet charts alike."""


def dollars(cents: int | None) -> float:
    """Minor units as dollars, for a chart's SCALE.

    Charts are drawn in dollars. Cents on the axis draw a $711,200 house
    at seventy million, and the mistake is invisible until a chart has a
    figure somebody knows by heart - so the conversion has one home
    rather than a ``/ 100`` in every series that gets written.
    """
    return (cents or 0) / 100
