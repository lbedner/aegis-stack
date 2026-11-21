"""Brand-palette parity across the tool and the generated app (issue #865).

The generated app has ONE palette, ``app/core/palette.json``: Tailwind
requires it, the Flet theme is built from it, the app's CLI reads it. The
tool's ``aegis/cli/brand.py`` cannot import the generated app (standalone
projects do not depend on the aegis tool), so it keeps its own literals;
this test is the guard that they never drift from the palette again.
"""

from __future__ import annotations

import json

from aegis.cli import brand
from aegis.core.component_files import get_template_path

PALETTE = get_template_path() / "{{ project_slug }}" / "app" / "core" / "palette.json"


def test_tool_palette_matches_the_apps_palette() -> None:
    """``aegis/cli/brand.py`` mirrors the generated app's dark palette."""
    dark = json.loads(PALETTE.read_text())["dark"]
    assert dark["primary"] == brand.AEGIS_TEAL
    assert dark["warning"] == brand.AEGIS_WARNING
    assert dark["error"] == brand.AEGIS_ERROR
