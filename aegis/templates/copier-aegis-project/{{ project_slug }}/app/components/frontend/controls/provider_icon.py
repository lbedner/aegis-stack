"""A small circular provider/merchant icon for a table row - a favicon
guess (``merchant_icon.py``, backend) when one resolves, an initial-letter
avatar when it doesn't. The guess is unverified (a domain heuristic, not a
real lookup), so a broken image is an expected, ordinary case here, not an
error - ``error_content`` is the fallback path, not a corner case.
"""

import flet as ft

from app.components.frontend.controls.text import SecondaryText
from app.components.frontend.theme import AegisTheme as Theme

_SIZE = 24
# Inset so a square logo doesn't touch the tile's rounded edge. Kept to a
# hair, because the tile CLIPS to its circle (below) - without that clip
# the padding has to be big enough to keep the logo's corners inside the
# circle on its own, and the largest square that fits inside a 24px circle
# is only 24/sqrt(2) ~= 17px. Paying 7px of the tile for corners that are
# never drawn left the logo visibly marooned in white space; clipping
# instead lets it run to the edge, which is what a circular avatar means.
_PAD = 1
# Near-white rather than pure white: still guarantees contrast for a
# black logo, without punching a hard white disc into a near-black row.
_TILE_BG = "#F2F2F2"


class ProviderIcon(ft.Container):
    """``name`` drives the initial-letter fallback; ``icon_b64`` is the
    resolved brand icon (or ``None``, which skips straight to the fallback
    - no point rendering an ``Image`` with nothing to show)."""

    def __init__(self, name: str, icon_b64: str | None) -> None:
        initial = (name or "?").strip()[:1].upper() or "?"
        fallback = ft.Container(
            # Sized up alongside the logo tile: these two share a row and a
            # circle, so a 10px letter next to a now edge-to-edge logo
            # reads as a different, smaller control rather than the same
            # one without a picture.
            content=SecondaryText(initial, size=Theme.Typography.BODY_SMALL),
            width=_SIZE,
            height=_SIZE,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            border_radius=_SIZE / 2,
            alignment=ft.alignment.center,
        )
        content: ft.Control = fallback
        if icon_b64:
            content = ft.Container(
                content=ft.Image(
                    # src_base64, never src: a remote URL is blocked by
                    # CORS and a relative one resolves against Flet's
                    # assets dir, not the HTTP origin (merchant_icon.py).
                    src_base64=icon_b64,
                    width=_SIZE - 2 * _PAD,
                    height=_SIZE - 2 * _PAD,
                    fit=ft.ImageFit.CONTAIN,
                    error_content=fallback,
                ),
                # A LIGHT tile behind every logo, not a theme-aware one.
                # Brand favicons are drawn for whatever background their
                # owner assumed, and plenty are near-black on transparency
                # - Paramount+'s icon is 13 opaque colours averaging
                # 13.6/255 luminance, i.e. invisible on this app's surface
                # while rendering perfectly. Detecting dark logos and
                # treating them differently would make the row read as
                # accidental; one constant tile makes every logo legible
                # no matter what it assumed, which is what every finance
                # app that shows merchant logos does.
                width=_SIZE,
                height=_SIZE,
                bgcolor=_TILE_BG,
                border_radius=_SIZE / 2,
                padding=_PAD,
                alignment=ft.alignment.center,
                # A Container never clips its child without being told to.
                # This is what lets the logo fill the tile: the corners a
                # square favicon would poke past the circle get cut by the
                # circle itself, the same way an avatar crops a photo.
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )
        super().__init__(content=content, width=_SIZE, height=_SIZE)
