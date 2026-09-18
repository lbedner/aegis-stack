"""Reading ``ComponentStatus.metadata`` without trusting its shape.

``metadata`` is ``dict[str, Any]`` and nothing validates it, so a card
gets whatever a health check published - which changes across upgrades,
and arrives in its own shape from a third-party plugin.

Its own module rather than ``card_utils``: that file is 659 lines of
recorded debt and may not grow, and this is a distinct concern anyway -
card_utils builds chrome, this reads payloads.
"""

from typing import Any

def metadata_number(metadata: dict[str, Any], key: str, default: float = 0) -> float:
    """A metadata value the card is about to format or compute with.

    ``.get(key, default)`` already covers the key being ABSENT, which is
    the common case and well tested. This covers it being PRESENT and
    the wrong type, which ``.get`` hands straight through:

        f"{metadata.get('hit_rate_percent', 0):.1f}%"
        ValueError: Unknown format code 'f' for object of type 'str'

    ``ComponentStatus.metadata`` is ``dict[str, Any]`` and nothing
    validates it, so the shape is whatever a health check publishes -
    and it changes across upgrades, or arrives from a third-party
    plugin. A raising card is not cosmetic either:
    ``update_component_cards`` builds cards inside the refresh loop, so
    one bad value takes out the whole cycle's card build rather than
    just its own tile.

    A wrong type therefore reads as the default, which is exactly what a
    missing key does. The card degrades to "0" instead of disappearing.
    """
    value = metadata.get(key, default)
    # bool is an int subclass, and a count of ``True`` is not a count.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return value


def metadata_text(metadata: dict[str, Any], key: str, default: str = "") -> str:
    """The same guard for a value the card calls string methods on.

    ``provider.lower()`` raises on anything that is not a string, and a
    card that cannot render its provider name should still render its
    other six fields.
    """
    value = metadata.get(key, default)
    return value if isinstance(value, str) else default
