"""
Auth service bracket-syntax parser.

R3 of the plugin system refactor: thin shim around the generic
``parse_options`` driven by the auth service's declarative ``options``
list. The typed ``AuthServiceConfig`` dataclass is preserved for
back-compat with existing callers.
"""

from dataclasses import dataclass
from typing import Any

from ..constants import AnswerKeys, AuthLevels
from .option_spec import is_spec_with_options, parse_options
from .services import SERVICES


@dataclass
class AuthServiceConfig:
    """Parsed auth service configuration (back-compat shape)."""

    level: str
    engine: str | None = None
    oauth: bool = False


def parse_auth_service_config(service_string: str) -> AuthServiceConfig:
    """Parse an ``auth[...]`` string into the legacy typed dataclass."""
    parsed = parse_options(service_string, SERVICES["auth"])
    return AuthServiceConfig(
        level=parsed["level"],
        engine=parsed.get("engine"),
        oauth=bool(parsed.get("oauth", False)),
    )


def is_auth_service_with_options(service_string: str) -> bool:
    """True when ``service_string`` uses ``auth[...]`` bracket syntax."""
    s = service_string.strip()
    return s.startswith("auth[") and is_spec_with_options(s)


def auth_level_answers(level: str) -> dict[str, Any]:
    """The answers an auth level implies: the level plus the two
    ``include_auth_*`` flags templates gate on. The single derivation,
    used wherever a level is set (``add-service auth[org]``, the
    resolver upgrading auth for a plugin, marker inference on update)."""
    return {
        AnswerKeys.AUTH_LEVEL: level,
        AnswerKeys.AUTH_RBAC: level in (AuthLevels.RBAC, AuthLevels.ORG),
        AnswerKeys.AUTH_ORG: level == AuthLevels.ORG,
    }
