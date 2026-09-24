"""Every dashboard card still renders what it used to.

Cards read ``ComponentStatus.metadata`` through ``.get(key, default)``,
so a field that stops being populated does not raise and does not fail a
test - it renders ``0``, ``-`` or blank. A backend modal read
``core_count`` while the health check published ``cpu_count``, and
advertised "0 cores" on every machine until somebody counted.

That is a refactor hazard more than a bug: moving a card between files,
or splitting one that has grown too large, can drop a metric and leave
every existing test green. So each card's rendered field COUNT is
recorded here, and the assertion is one-directional - a card may grow,
but it may not quietly shrink. Counts rather than exact copy, so
rewording a label is not a test failure; losing the label is.

The cards are discovered, not listed, so a stack tests the cards it
actually has. A card with no recorded number belongs to a plugin - plugins
install cards into this package, and cannot edit a file the framework
regenerates - so its count check is skipped; every other check still runs
on it. The framework's own cards are held to the table by its repository
test suite, so a first-party card can never slip through as a plugin's.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import sys

import pytest

import app.components.frontend.dashboard.cards as cards_package
from app.services.system.models import ComponentStatus
from tests.components.frontend._tree import texts

# Fields each card renders from an EMPTY metadata payload - its labels,
# its status, and whatever its defaults produce. Empty rather than
# populated because that is the shape every stack agrees on: what a card
# is given varies with which health checks a project runs.
MINIMUM_FIELDS: dict[str, int] = {
    "AICard": 9,
    "AuthCard": 9,
    "BlogCard": 9,
    "CommsCard": 9,
    "DatabaseCard": 9,
    "DocumentsCard": 9,
    "FinanceCard": 9,
    "InsightsCard": 9,
    "IngressCard": 6,
    "ObservabilityCard": 6,
    "OllamaCard": 9,
    "PaymentCard": 9,
    "RedisCard": 9,
    "SchedulerCard": 10,
    "ServerCard": 9,
    "ServicesCard": 14,
    "StorageCard": 7,
    "WorkerCard": 10,
}


def discovered_cards() -> list[tuple[str, type]]:
    """Every card class this project actually ships."""
    found: list[tuple[str, type]] = []
    for module_info in pkgutil.iter_modules(cards_package.__path__):
        if not module_info.name.endswith("_card"):
            continue
        module = importlib.import_module(
            f"app.components.frontend.dashboard.cards.{module_info.name}"
        )
        for name, obj in vars(module).items():
            if (
                inspect.isclass(obj)
                and name.endswith("Card")
                and obj.__module__ == module.__name__
                and not inspect.isabstract(obj)
            ):
                found.append((name, obj))
    return sorted(found)


CARDS = discovered_cards()
CARD_IDS = [name for name, _ in CARDS]


def status(name: str, state: str = "healthy", **metadata: object) -> ComponentStatus:
    return ComponentStatus(
        name=name,
        status=state,
        message="ok",
        response_time_ms=1.0,
        metadata=dict(metadata),
    )


def rendered(card_cls: type, data: ComponentStatus) -> list[str]:
    return texts(card_cls(data).build())


def test_cards_were_found() -> None:
    """Guard the guard. Discovery that silently found nothing would pass
    every parametrised test below by having none to run."""
    assert CARDS, "no dashboard cards discovered; the module scan drifted"


class TestEveryCardRenders:
    @pytest.mark.parametrize("name,card_cls", CARDS, ids=CARD_IDS)
    def test_it_builds_with_no_metadata_at_all(self, name: str, card_cls: type) -> None:
        """The realistic failure: a health check stops publishing, or a
        stack never ran it. A card must degrade, not crash."""
        assert rendered(card_cls, status(name.replace("Card", "").lower()))

    @pytest.mark.parametrize("name,card_cls", CARDS, ids=CARD_IDS)
    def test_it_did_not_lose_fields(self, name: str, card_cls: type) -> None:
        if name not in MINIMUM_FIELDS:
            pytest.skip(f"{name} is a plugin's card; its count is not recorded here")
        count = len(rendered(card_cls, status(name.replace("Card", "").lower())))
        assert count >= MINIMUM_FIELDS[name], (
            f"{name} renders {count} fields, down from {MINIMUM_FIELDS[name]}. "
            f"A field disappeared. If that was deliberate, lower the number."
        )

    @pytest.mark.parametrize("name,card_cls", CARDS, ids=CARD_IDS)
    def test_every_field_it_renders_says_something(
        self, name: str, card_cls: type
    ) -> None:
        """A card padded with blanks passes a count check while showing
        the user nothing."""
        fields = rendered(card_cls, status(name.replace("Card", "").lower()))
        assert all(f.strip() for f in fields)


# Cards that legitimately do not render their component's own status.
# ServicesCard reports the state of each registered service from
# metadata; the aggregate status it is handed is not what it shows.
STATUS_IS_NOT_SHOWN = {"ServicesCard"}


class TestStatusReachesTheCard:
    @pytest.mark.parametrize("name,card_cls", CARDS, ids=CARD_IDS)
    def test_an_unhealthy_component_renders_differently(
        self, name: str, card_cls: type
    ) -> None:
        """The card's whole job. If a refactor stops threading status
        through, every card renders healthy forever and the dashboard
        lies quietly."""
        if name in STATUS_IS_NOT_SHOWN:
            pytest.skip(f"{name} renders per-item state, not its own status")

        component = name.replace("Card", "").lower()
        healthy = rendered(card_cls, status(component))
        unhealthy = rendered(card_cls, status(component, "unhealthy"))

        assert healthy != unhealthy, (
            f"{name} renders identically whether the component is healthy or unhealthy"
        )


# Values a health check could plausibly publish where a card expects a
# number. A string is the realistic one - a field that used to be an int
# becomes "12.4%" or "unknown" across an upgrade, or a third-party
# plugin publishes metadata in its own shape - and it is what breaks
# ``f"{value:.1f}"`` and arithmetic alike.
HOSTILE_VALUES = ["unexpected-string", None, [], {}]

_METADATA_READ = re.compile(r"""metadata\.get\(\s*["']([A-Za-z_0-9]+)["']""")


def keys_a_card_reads(card_cls: type) -> set[str]:
    """Every metadata key named in the card's own module."""
    return set(
        _METADATA_READ.findall(inspect.getsource(sys.modules[card_cls.__module__]))
    )


class TestEveryCardSurvivesAWrongType:
    """The other half of the degrade contract.

    The class above covers metadata that is MISSING, which is well
    handled: every read is ``.get(key, default)``. Nothing covers
    metadata that is PRESENT and the wrong type, and ``.get`` hands that
    straight through:

        RedisCard._get_hit_ratio_display
            return f"{hit_rate:.1f}%"
        ValueError: Unknown format code 'f' for object of type 'str'

    That is not cosmetic. ``update_component_cards`` builds cards inside
    the refresh loop, so one bad value takes out the card build for the
    whole cycle, not just its own tile.

    The keys are scraped from each card's source rather than listed, for
    the same reason the cards are discovered rather than listed: a card
    that starts reading a new key is covered without anyone remembering
    to add it here.
    """

    @pytest.mark.parametrize("name,card_cls", CARDS, ids=CARD_IDS)
    @pytest.mark.parametrize("hostile", HOSTILE_VALUES, ids=repr)
    def test_it_builds_when_every_value_is_the_wrong_type(
        self, name: str, card_cls: type, hostile: object
    ) -> None:
        keys = keys_a_card_reads(card_cls)
        if not keys:
            pytest.skip(f"{name} reads no metadata keys")
        payload = dict.fromkeys(keys, hostile)
        component = name.replace("Card", "").lower()
        assert rendered(card_cls, status(component, **payload))
