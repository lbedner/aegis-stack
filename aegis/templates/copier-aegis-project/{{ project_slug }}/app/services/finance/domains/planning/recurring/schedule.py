"""When a stream is expected to move money, answered once.

Every surface that looks forward - the projection walk, the month-ahead
outlook - needs the same list of dates out of a stream, and each grew its
own loop. The loops drifted, always the same way: a rule the recurring
branch honoured and the one-time branch did not, or the reverse. Overdue
bills vanished from the outlook entirely and from one side of the
forecast, so a month showing $4,431 due quietly excluded the $1,000
already late.

The rules live here now, and callers decide only what to do with what
comes back.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.services.finance.constants import ONE_TIME_FREQUENCY
from app.services.finance.utils import FREQUENCY_STEPS

# A cadence that steps by a day would still terminate inside any sane
# window; this stops a malformed step function from spinning forever.
_MAX_STEPS = 400


class _Scheduled(Protocol):
    """The two fields a schedule reads off a stream."""

    frequency: str
    next_expected_date: date | None


@dataclass(frozen=True)
class Occurrence:
    """One expected movement of money.

    `lands_on` is where it belongs in a forward walk; `due_on` is the day
    it was actually owed. They differ only for money already late, which
    lands on today but must still show the date it slipped.
    """

    lands_on: date
    due_on: date

    @property
    def is_overdue(self) -> bool:
        return self.due_on < self.lands_on


def occurrences(
    stream: _Scheduled, *, today: date, through: date
) -> Iterator[Occurrence]:
    """Every expected movement from `today` through `through`, inclusive.

    Anything already past due lands on today rather than disappearing:
    it is money still owed, and a walk that skips it spends a balance the
    payment never left. Only the most recent miss carries - older ones
    have already settled into today's balance.
    """
    when = stream.next_expected_date
    if when is None:
        return

    if stream.frequency == ONE_TIME_FREQUENCY:
        # No cadence to step, so a missed one-time bill has no later
        # occurrence to carry it. Without this it would simply vanish.
        if when < today:
            yield Occurrence(lands_on=today, due_on=when)
        elif when <= through:
            yield Occurrence(lands_on=when, due_on=when)
        return

    step = FREQUENCY_STEPS.get(stream.frequency)
    if step is None:
        return

    guard = 0
    while when < today and guard < _MAX_STEPS:
        nxt = step(when)
        # ``>=``, not ``>``: a weekly bill missed last Thursday and due
        # again exactly today is two debts, and the older one still has
        # to arrive with the date it slipped.
        if nxt >= today:
            yield Occurrence(lands_on=today, due_on=when)
        when = nxt
        guard += 1
    while when <= through and guard < _MAX_STEPS:
        yield Occurrence(lands_on=when, due_on=when)
        when = step(when)
        guard += 1
