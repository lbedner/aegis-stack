"""Automatic service attribution, using the existing app/services convention.

The emitting service and exception origin are separate. Inspect live exception
objects before formatting destroys frame metadata; follow explicit causes and
unsuppressed contexts. Job wrappers preserve ownership when frames are shared.
"""

import re
import sys
from typing import Any

from app.core.constants import ServiceName

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
ORIGIN_ATTRIBUTE = "_aegis_error_service"


def registered_service(name: object) -> bool:
    """Built-in specs and registered plugin services, without booting health checks."""
    if not isinstance(name, str):
        return False
    if name in ServiceName:
        return True
    health = sys.modules.get("app.services.system.health")
    registry = getattr(health, "registered_health_names", None)
    return registry is not None and name in registry()["services"]


def service_from_path(pathname: str) -> str | None:
    """Extract app/services/<owner>/<file>, independent of deployment root."""
    parts = pathname.replace("\\", "/").split("/")
    for index in range(len(parts) - 3):
        if parts[index : index + 2] == ["app", "services"]:
            name = parts[index + 2]
            if NAME.fullmatch(name) and registered_service(name):
                return name
    return None


def exception_origin(error: BaseException) -> str | None:
    """Deepest chained cause with service evidence; guard against chain cycles."""
    seen: set[int] = set()
    origin = None
    while id(error) not in seen and len(seen) < 64:
        seen.add(id(error))
        current = getattr(error, ORIGIN_ATTRIBUTE, None)
        trace = error.__traceback__ if not isinstance(current, str) else None
        while trace is not None:
            owner = service_from_path(trace.tb_frame.f_code.co_filename)
            if owner:
                current = owner
            trace = trace.tb_next
        if isinstance(current, str):
            origin = current
        cause = error.__cause__ or (
            error.__context__ if not error.__suppress_context__ else None
        )
        if cause is None:
            break
        error = cause
    return origin


def remember_exception_origin(error: Exception, owner: str | None) -> None:
    """Keep job ownership available after its scoped context has unwound."""
    origin = exception_origin(error) or owner
    if origin:
        error.__dict__.setdefault(ORIGIN_ATTRIBUTE, origin)


def add_service_attribution(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """A processor shared by structlog and standard-library logging."""
    emitter = service_from_path(str(event_dict.get("pathname", "")))
    if emitter:
        event_dict["emitting_service"] = emitter
    error = event_dict.get("exc_info")
    if error is True:
        error = sys.exc_info()[1]
    elif isinstance(error, tuple) and len(error) == 3:
        error = error[1]
    origin = exception_origin(error) if isinstance(error, BaseException) else None
    scoped = event_dict.get("app_service")
    owner = origin or (scoped if registered_service(scoped) else None) or emitter
    if registered_service(owner):
        event_dict["app_service"] = owner
    else:
        event_dict.pop("app_service", None)
    return event_dict
