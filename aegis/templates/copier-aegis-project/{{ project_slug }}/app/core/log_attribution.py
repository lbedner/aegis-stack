"""Automatic service and component attribution, by who owns the code a
line or an exception came from (``ownership``).

The emitting service and exception origin are separate. Inspect live exception
objects before formatting destroys frame metadata; follow explicit causes and
unsuppressed contexts. Job wrappers preserve ownership when frames are shared.
"""

import sys
from types import TracebackType
from typing import Any

from app.core.ownership import SERVICE, SHARED, installed, owner

ORIGIN_ATTRIBUTE = "_aegis_error_service"
# The service and the component a file or a traceback belongs to.
Owners = tuple[str | None, str | None]


def _owners(pathname: str) -> Owners:
    """Who owns a file, wherever the app is deployed: its service or its
    component (``ownership.owner``), each None if not that kind."""
    found = owner(pathname)
    if found is None or found.kind == SHARED:
        return None, None
    return (found.name, None) if found.kind == SERVICE else (None, found.name)


def service_from_path(pathname: str) -> str | None:
    return _owners(pathname)[0]


def _deepest(trace: TracebackType | None) -> Owners:
    """The innermost frame's service, and the innermost frame's component,
    in ``trace``: each frame's owner looked up once."""
    service = component = None
    while trace is not None:
        here, there = _owners(trace.tb_frame.f_code.co_filename)
        service, component = here or service, there or component
        trace = trace.tb_next
    return service, component


def exception_origin(error: BaseException) -> str | None:
    """Deepest chained cause with service evidence; guard against chain cycles."""
    return _origins(error)[0]


def _origins(error: BaseException) -> Owners:
    """The deepest chained cause's service (one a job kept wins), and the
    component ``error`` itself broke in or passed through last; chain
    cycles guarded."""
    seen: set[int] = set()
    origin = component = None
    while id(error) not in seen and len(seen) < 64:
        current = getattr(error, ORIGIN_ATTRIBUTE, None)
        if not seen or not isinstance(current, str):
            service, found = _deepest(error.__traceback__)
            component = found if not seen else component
            current = current if isinstance(current, str) else service
        seen.add(id(error))
        if isinstance(current, str):
            origin = current
        cause = error.__cause__ or (
            error.__context__ if not error.__suppress_context__ else None
        )
        if cause is None:
            break
        error = cause
    return origin, component


def remember_exception_origin(error: Exception, owner: str | None) -> None:
    """Keep job ownership available after its scoped context has unwound."""
    origin = exception_origin(error) or owner
    if origin:
        error.__dict__.setdefault(ORIGIN_ATTRIBUTE, origin)


def add_service_attribution(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """A processor shared by structlog and standard-library logging."""
    emitter, emitting_component = _owners(str(event_dict.get("pathname", "")))
    if emitter:
        event_dict["emitting_service"] = emitter
    error = event_dict.get("exc_info")
    if error is True:
        error = sys.exc_info()[1]
    elif isinstance(error, tuple) and len(error) == 3:
        error = error[1]
    origin, component = (
        _origins(error) if isinstance(error, BaseException) else (None, None)
    )
    if component := component or emitting_component:
        event_dict["app_component"] = component
    scoped = event_dict.get("app_service")
    chosen = origin or (scoped if installed(SERVICE, scoped) else None) or emitter
    if installed(SERVICE, chosen):
        event_dict["app_service"] = chosen
    else:
        event_dict.pop("app_service", None)
    return event_dict
