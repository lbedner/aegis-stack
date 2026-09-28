"""Every card opens a modal that exists.

Cards and modals meet on one string: the card's ``component_name`` is the
key the modal registers under. Three service cards shipped with a bare
name while their modals were keyed by the health-tree id, and the click
was a silent no-op for months. This walks every card so that class of
gap fails here instead.
"""

from app.components.frontend.dashboard import cards
from app.components.frontend.dashboard.modal_registry import modal_registry
from app.services.system.models import ComponentStatus, ComponentStatusType

# The aggregate card expands the services group in place; it has no modal.
_NO_MODAL = {"ServicesCard"}


def test_every_card_routes_to_a_registered_modal() -> None:
    registry = modal_registry()
    for name in cards.__all__:
        if name in _NO_MODAL:
            continue
        card = getattr(cards, name)(
            ComponentStatus(
                name=name, status=ComponentStatusType.HEALTHY, message="ok", metadata={}
            )
        ).build()
        assert card.component_name in registry, (
            f"{name} opens {card.component_name!r}, which no modal registers under"
        )


def test_components_without_a_card_are_skipped_quietly() -> None:
    """Both frontends are shown through the Server card. Neither may fall
    through to the "Unknown component" placeholder, which logged a warning
    on every dashboard refresh for web_frontend."""
    from app.components.frontend.overseer.cards import create_component_card

    for name in ("frontend", "web_frontend"):
        status = ComponentStatus(
            name=name, status=ComponentStatusType.HEALTHY, message="ok", metadata={}
        )
        assert create_component_card(name, status).content is None, name
