"""The dashboard's component cards, held by name and rebuilt only when
their component actually changed.

Flet keeps the control tree server-side and sends the browser a diff, but
it can only do that when the control OBJECTS survive between updates. The
dashboard used to clear its card row and rebuild all eighteen cards every
thirty seconds, per connected session, so there was nothing to diff
against: Flet saw an entirely new subtree and transmitted a full
replacement, and the browser tore down and rebuilt the widgets.

Measured before this existed: two consecutive builds of one card share
none of their 32 controls, and in the steady state the rendered strings
are identical on both sides of the cycle. That is 576 control objects
discarded every thirty seconds to change nothing, which is what a healthy
board does for most of its life.

So the cards are kept, along with the status each was built from. A
component whose status is byte-identical keeps its card untouched, object
and all.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from app.services.system.models import ComponentStatus

# All cards use uniform 1/3 width (3-column grid).
CARD_COLUMNS = {"xs": 12, "sm": 6, "md": 4, "lg": 4, "xl": 4}


class CardRegistry:
    """Component cards by name, plus the status each was rendered from."""

    def __init__(self) -> None:
        self._cards: dict[str, ft.Control] = {}
        self._statuses: dict[str, ComponentStatus] = {}
        # The creator the last sync used. A surface holding a fresh
        # status - the Ollama modal, say - can then apply it without
        # having to be handed the dashboard's card factory too.
        self._creator: Callable[[str, ComponentStatus], ft.Control] | None = None

    def sync(
        self,
        components: dict[str, ComponentStatus],
        card_creator_fn: Callable[[str, ComponentStatus], ft.Control],
    ) -> list[ft.Control]:
        """Return the row's controls, rebuilding only what changed.

        ``ComponentStatus`` is a pydantic model with value equality over
        its metadata, so "did this component change" is an exact
        comparison rather than a heuristic.
        """
        self._creator = card_creator_fn
        self._forget_departed(components)

        controls: list[ft.Control] = []
        for name, data in components.items():
            card = self._cards.get(name)
            if card is None or self._statuses.get(name) != data:
                card = self._build(name, data, card_creator_fn)
                if card is None:
                    # Renders nothing, so it holds no slot and keeps no
                    # cached status to be compared against next cycle.
                    self._cards.pop(name, None)
                    self._statuses.pop(name, None)
                    continue
                self._cards[name] = card
                self._statuses[name] = data
            controls.append(card)
        return controls

    def apply(self, name: str, data: ComponentStatus) -> bool:
        """Rebuild one component's card in place. True when it changed.

        Returns False for a component this board does not show, and
        before the first sync, when there is no creator and no slot to
        put a card in.
        """
        if self._creator is None or name not in self._cards:
            return False
        if self._statuses.get(name) == data:
            return False
        card = self._build(name, data, self._creator)
        if card is None:
            return False
        self._cards[name] = card
        self._statuses[name] = data
        return True

    def controls(self) -> list[ft.Control]:
        """The cards in the order the last sync arranged them."""
        return [self._cards[name] for name in self._statuses if name in self._cards]

    def _forget_departed(self, components: dict[str, ComponentStatus]) -> None:
        """Drop what is no longer reported.

        A component that disappears takes its cached status with it, so
        it cannot be mistaken for unchanged if it comes back.
        """
        for name in list(self._statuses):
            if name not in components:
                self._cards.pop(name, None)
                self._statuses.pop(name, None)

    @staticmethod
    def _build(
        name: str,
        data: ComponentStatus,
        card_creator_fn: Callable[[str, ComponentStatus], ft.Control],
    ) -> ft.Control | None:
        """One component's card, or None when it renders nothing."""
        card = card_creator_fn(name, data)

        # Skip empty cards (e.g. frontend merged into ServerCard).
        if not card.content:
            return None

        if (
            isinstance(card.content, ft.Text)
            and "Unknown component" in card.content.value
        ):
            return None  # Skip unknown components

        card.col = CARD_COLUMNS
        return card
