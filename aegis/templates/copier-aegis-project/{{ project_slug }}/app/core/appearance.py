"""The look both frontends and the CLI share: one palette, one stored mode.

``palette.json`` is also what ``tailwind.config.js`` requires for the htmx
build, so a colour changes in one place.
"""

import json
from pathlib import Path

PALETTE: dict[str, dict[str, str]] = json.loads(
    Path(__file__).with_name("palette.json").read_text()
)

# Where each frontend keeps the light/dark choice: htmx's localStorage key
# (``web_frontend/static/js/theme.js``) and the Flet client-storage key
# ``ThemeManager`` reads. The dashboard's mode bridge copies one to the other.
HTMX_MODE_KEY = "mode"
FLET_MODE_KEY = "aegis.mode"
