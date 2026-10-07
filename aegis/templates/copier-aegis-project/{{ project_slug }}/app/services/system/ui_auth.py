"""What the authentication detail views show, for every frontend.

Read from the auth health check's metadata. States carry a semantic colour
name (green, blue, yellow, red), the vocabulary ``get_status_color_name``
already uses, so each frontend maps them to its own theme.
"""

import re
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


# Browsers by the token their user-agent string names them with, the most
# specific first: Edge also says Chrome, and Chrome also says Safari.
_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("Version/", "Safari"),
)
# Systems likewise: an iPhone also says Mac OS X, Android also says Linux.
_SYSTEMS = (
    ("iPhone", "iOS"),
    ("iPad", "iOS"),
    ("Android", "Android"),
    ("Mac OS X", "macOS"),
    ("Windows", "Windows"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)
_PRODUCT = re.compile(r"^([\w.-]+)/(\S+)")  # a script's ``name/version``


def device_label(user_agent: str | None) -> str:
    """A session's device as its browser, major version and system
    (``Chrome 154 · macOS``), a script as its name and version, else the
    string as it came: the whole user-agent string is too long to read."""
    if not user_agent:
        return "Unknown device"
    browser = next((pair for pair in _BROWSERS if pair[0] in user_agent), None)
    system = next((name for token, name in _SYSTEMS if token in user_agent), None)
    if browser and system:
        token, name = browser
        major = user_agent.split(token, 1)[1].split(".", 1)[0].split(" ", 1)[0]
        return f"{name} {major} · {system}"
    product = _PRODUCT.match(user_agent)
    if product and not user_agent.startswith("Mozilla/"):
        return f"{product[1]} {product[2]}"
    return user_agent


def session_source(source: str | None) -> tuple[str, str]:
    """How a session signed in, and its colour."""
    return _SOURCES.get(source or "", (source or "Unknown", "yellow"))


# Deletes are soft: the row keeps ``deleted_at`` and ``.../restore`` brings it
# back, so neither confirmation may promise the delete is permanent.
def delete_user_confirmation(email: str) -> tuple[str, str]:
    """The title and body of the delete-user confirmation."""
    return (
        "Delete user",
        f"Delete {email}? They leave the user list and can no longer sign in.",
    )


def revoke_session_confirmation(user_agent: str | None) -> tuple[str, str]:
    """The title and body of the sign-out-this-device confirmation."""
    device = device_label(user_agent) if user_agent else "this device"
    return (
        "Sign out this device",
        f"Sign out {device}? It is signed out on its next request.",
    )


def delete_org_confirmation(name: str) -> tuple[str, str]:
    """The title and body of the delete-organization confirmation."""
    return (
        "Delete organization",
        f"Delete {name}? It leaves the organization list, and its memberships "
        "and pending invites are removed for good.",
    )
