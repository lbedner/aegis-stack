"""Which combinations the stack matrix never builds.

Seven bugs shipped on `main` with green CI because the combination that
broke them was never generated. Every one was found by hand, months
apart, by someone happening to pick that shape:

* `--services "ai"` — the DEFAULT backend — died on import
* `ai[voice]` died on import
* `finance` + `auth[rbac]` could not migrate at all
* `finance` + `ai` shipped a local-clock read past a guard written to
  catch exactly that, because the guarded file only renders with both
* `documents` + `auth` shipped 22 failing API tests (#1179)
* the Ollama surface has never been built by anything (#1183)
* the queryspy sweep was a silent no-op

The matrix is a hand-maintained list, so a gap in it is invisible: a
check cannot go red over a stack nobody wrote down. Adding one row per
bug discovered is how the first seven were handled, and it only ever
covers the shape that already burned someone.

This computes the gaps instead. The universe comes from the SERVICES
registry, not from a list here, so a new service or a new option value
enrolls itself the moment it is declared and shows up as uncovered
until someone decides otherwise.

UNCOVERED_* are RATCHETS, in the manner of `test_module_size_budget`:
they record the gaps that exist today so the backlog does not block
work, and the test fails when a NEW one appears. Adding a service or an
option value is then a decision — cover it, or write it down — rather
than a silence. Cover a recorded gap and the test tells you to delete
its entry, so the lists can only shrink.

Running these combinations is not the point and would cost hours of CI;
knowing which ones nobody has ever run is.
"""

from __future__ import annotations

import itertools
import re

from aegis.core.option_spec import OptionMode
from aegis.core.services import SERVICES
from tests.cli.test_stack_generation import STACK_COMBINATIONS

# Service pairs no stack in the matrix builds together. Empty, and worth
# keeping that way: `everything` carries every service, so every pair is
# built somewhere. A new service arrives uncovered against all eight and
# fails the test below until it is added there or recorded here.
UNCOVERED_SERVICE_PAIRS: set[tuple[str, str]] = set()

# Option values no stack resolves to, defaults included: a stack that
# writes bare ``ai`` still exercises that service's default framework,
# backend and providers, so only genuinely unreached values are here.
UNCOVERED_OPTION_VALUES: set[str] = {
    # Credential-shaped providers: the client is built from a key and
    # brings no surface of its own to render, so a row each buys little
    # that ``openai`` does not already cover. Ollama WAS the exception -
    # it ships a card, a modal and a health check - and has its own row.
    "ai.providers=anthropic",
    "ai.providers=cohere",
    "ai.providers=google",
    "ai.providers=groq",
    "ai.providers=mistral",
    # Needs a postgres service in CI, unlike every sqlite row here. The
    # engine-specific code it would exercise is the database component's,
    # which its own matrix rows already cover.
    "ai.backend=postgres",
    # Not reachable through the service bracket as the matrix uses it:
    # ``auth.engine`` defaults to None and the engine is pinned by the
    # ``database[...]`` component instead, so no StackCombination names
    # it. Covering these means changing how auth picks an engine, not
    # adding a row.
    "auth.engine=postgres",
    "auth.engine=sqlite",
}

_ENTRY = re.compile(r"([\w-]+)(?:\[(.*)\])?$")


def _parse(entry: str) -> tuple[str, list[str]]:
    """``"ai[sqlite,voice]"`` -> ``("ai", ["sqlite", "voice"])``."""
    match = _ENTRY.match(entry)
    if match is None:
        raise ValueError(f"unparseable service entry: {entry!r}")
    written = match.group(2) or ""
    return match.group(1), [o.strip() for o in written.split(",") if o.strip()]


def _covered_service_pairs() -> set[tuple[str, str]]:
    """Every service pair some stack generates together."""
    covered: set[tuple[str, str]] = set()
    for combination in STACK_COMBINATIONS:
        names = sorted({_parse(s)[0] for s in combination.services or []})
        covered.update(itertools.combinations(names, 2))
    return covered


def _all_service_pairs() -> set[tuple[str, str]]:
    return set(itertools.combinations(sorted(SERVICES), 2))


def _reached_option_values() -> set[str]:
    """Option values stacks actually resolve to, defaults included.

    A bracket that names no value for an option still exercises that
    option's default, which is why ``ai[voice]`` covers
    ``ai.backend=memory``.
    """
    reached: set[str] = set()
    for combination in STACK_COMBINATIONS:
        for entry in combination.services or []:
            name, written = _parse(entry)
            spec = SERVICES.get(name)
            if spec is None:
                continue
            for option in getattr(spec, "options", []) or []:
                picked = [w for w in written if w in option.choices]
                if option.mode == OptionMode.FLAG:
                    reached.add(f"{name}.{option.name}={bool(picked)}")
                elif picked:
                    reached.update(f"{name}.{option.name}={v}" for v in picked)
                else:
                    default = option.default
                    values = default if isinstance(default, list) else [default]
                    reached.update(f"{name}.{option.name}={v}" for v in values)
    return reached


def _all_option_values() -> set[str]:
    values: set[str] = set()
    for name, spec in SERVICES.items():
        for option in getattr(spec, "options", []) or []:
            choices = (
                [True, False] if option.mode == OptionMode.FLAG else option.choices
            )
            values.update(f"{name}.{option.name}={v}" for v in choices)
    return values


def test_no_new_service_pair_goes_unbuilt() -> None:
    """A newly uncovered pair means a service landed without coverage."""
    uncovered = _all_service_pairs() - _covered_service_pairs()
    new = sorted(uncovered - UNCOVERED_SERVICE_PAIRS)
    assert not new, (
        "Service pairs nothing in the matrix builds together:\n  "
        + "\n  ".join(f"{a} + {b}" for a, b in new)
        + "\n\nAdd a StackCombination pairing them, or record the pair in "
        "UNCOVERED_SERVICE_PAIRS to say the gap is known and accepted."
    )


def test_no_new_option_value_goes_unbuilt() -> None:
    """A newly unreached value means an option landed without coverage."""
    unreached = _all_option_values() - _reached_option_values()
    new = sorted(unreached - UNCOVERED_OPTION_VALUES)
    assert not new, (
        "Option values no stack in the matrix ever resolves to:\n  "
        + "\n  ".join(new)
        + "\n\nName the value in a StackCombination's service bracket, or "
        "record it in UNCOVERED_OPTION_VALUES to accept the gap."
    )


def test_recorded_service_pair_gaps_are_still_gaps() -> None:
    """Cover a recorded pair and its entry has to go, or it hides a gap."""
    uncovered = _all_service_pairs() - _covered_service_pairs()
    stale = sorted(UNCOVERED_SERVICE_PAIRS - uncovered)
    assert not stale, (
        "These pairs ARE built now. Delete them from "
        "UNCOVERED_SERVICE_PAIRS:\n  " + "\n  ".join(f"{a} + {b}" for a, b in stale)
    )


def test_recorded_option_gaps_are_still_gaps() -> None:
    """Same ratchet for option values: covered means the entry goes."""
    unreached = _all_option_values() - _reached_option_values()
    stale = sorted(UNCOVERED_OPTION_VALUES - unreached)
    assert not stale, (
        "These values ARE reached now. Delete them from "
        "UNCOVERED_OPTION_VALUES:\n  " + "\n  ".join(stale)
    )


def test_every_recorded_gap_names_something_real() -> None:
    """The lists cannot outlive the services they name.

    Delete a service and its entries become unfalsifiable: neither
    uncovered nor stale, just noise that reads like tracked debt.
    """
    known_pairs = _all_service_pairs()
    orphan_pairs = sorted(UNCOVERED_SERVICE_PAIRS - known_pairs)
    known_values = _all_option_values()
    orphan_values = sorted(UNCOVERED_OPTION_VALUES - known_values)
    assert not orphan_pairs and not orphan_values, (
        "Recorded gaps that name nothing in the registry:\n  "
        + "\n  ".join([f"{a} + {b}" for a, b in orphan_pairs] + orphan_values)
        + "\n\nThe service or option is gone; delete the entry."
    )
