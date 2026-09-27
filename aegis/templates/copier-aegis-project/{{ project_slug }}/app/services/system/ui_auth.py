"""What the authentication detail views show, for every frontend.

Read from the auth health check's metadata. States carry a semantic colour
name (green, blue, yellow, red), the vocabulary ``get_status_color_name``
already uses, so each frontend maps them to its own theme.
"""

from typing import Any

_SECURITY = {
    "high": ("Strong security with robust encryption.", "green"),
    "standard": (
        "Adequate security. Consider RS256/ES256 for better security.",
        "blue",
    ),
    "basic": ("Minimal security. Improve secret key strength.", "yellow"),
}

_SOURCES = {
    "password": ("Password", "blue"),
    "oauth:github": ("GitHub", "green"),
    "oauth:google": ("Google", "green"),
}


def key_strength(length: int) -> tuple[str, str]:
    """The signing key's strength label and colour, by its length."""
    if length >= 64:
        return "Strong", "green"
    if length >= 32:
        return "Moderate", "yellow"
    return "Weak", "red"


def security_level(metadata: dict[str, Any]) -> tuple[str, str, str]:
    """The security level, what it means, and its colour."""
    level = str(metadata.get("security_level", "basic"))
    description, color = _SECURITY.get(
        level, ("Unknown security configuration.", "yellow")
    )
    return level, description, color


def session_source(source: str | None) -> tuple[str, str]:
    """How a session signed in, and its colour."""
    return _SOURCES.get(source or "", (source or "Unknown", "yellow"))
