"""The payee icon renders once and stays rendered.

``src_base64`` decodes to a FRESH byte buffer every time a virtualized
row remounts, and Flutter's image cache keys memory images by buffer
identity - so every scroll-back-in was a cache miss, an async re-decode,
and one visible frame of empty tile (confirmed live: "they keep
flickering as I scroll, as if they keep loading"). The same bytes as a
``data:`` URI on ``src`` are a stable STRING, which is exactly what the
cache keys network images by: decoded once, cached, no flicker. The
constraints that killed URL icons (CORS on third-party hosts, Flet
resolving relative paths against the assets dir) do not apply - nothing
is fetched and the scheme is explicit.
"""

import flet as ft

from app.components.frontend.controls.provider_icon import ProviderIcon


def _image(icon: ProviderIcon) -> ft.Image:
    tile = icon.content
    assert isinstance(tile, ft.Container)
    image = tile.content
    assert isinstance(image, ft.Image)
    return image


class TestTheIconIsCacheable:
    def test_the_bytes_ride_as_a_data_uri_not_a_buffer(self) -> None:
        image = _image(ProviderIcon("Amex", "aGVsbG8="))
        assert image.src == "data:image/png;base64,aGVsbG8="
        assert image.src_base64 is None

    def test_the_uri_is_stable_across_builds(self) -> None:
        """String equality is the whole mechanism - two renders of the
        same icon must produce the identical cache key."""
        a = _image(ProviderIcon("Amex", "aGVsbG8="))
        b = _image(ProviderIcon("Amex", "aGVsbG8="))
        assert a.src == b.src

    def test_no_icon_still_falls_back_to_the_initial(self) -> None:
        icon = ProviderIcon("Amex", None)
        assert not isinstance(icon.content.content, ft.Image)

    def test_a_broken_icon_still_has_its_error_fallback(self) -> None:
        image = _image(ProviderIcon("Amex", "aGVsbG8="))
        assert image.error_content is not None
