"""Context for the Overseer Ingress page: Traefik, read live from its API.

The Overview draws how a request travels through each of the app's
routers (entrypoint, rule, middlewares, service, servers); the other
sections list routers, services and middlewares in full. Traefik's own
routers (provider ``internal``: its API and dashboard) are listed but not
drawn as app traffic.
"""

import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.core.log import logger
from app.services.system.models import ComponentStatus

from .overseer_nav import SectionRequest
from .rendering import status_cell

SECTIONS = (
    (None, {"overview": "Overview"}),
    (
        "Traffic",
        {"routers": "Routers", "services": "Services", "middlewares": "Middlewares"},
    ),
)

ENDPOINTS = {
    "version": "/api/version",
    "entrypoints": "/api/entrypoints",
    "routers": "/api/http/routers",
    "services": "/api/http/services",
    "middlewares": "/api/http/middlewares",
}
# Fields every middleware carries; whatever else it has is its settings.
_MIDDLEWARE_META = {"name", "type", "status", "provider", "usedBy", "error"}
_SERVER_TONES = {"UP": "ok", "DOWN": "error"}
# An allowlist containing one of these admits every address.
OPEN_RANGES = frozenset({"0.0.0.0/0", "::/0"})
AUTH_TYPES = frozenset({"basicauth", "digestauth", "forwardauth"})
# Traefik's own API and dashboard.
ADMIN_SERVICES = frozenset({"api@internal", "dashboard@internal"})
# Traefik gives its internal routers priorities near the int64 maximum.
HIGHEST_PRIORITY = 2**62


async def fetch_traefik() -> dict[str, Any]:
    """Every endpoint the page reads, fetched at once. Raises when Traefik
    cannot be reached or answers with an error."""
    # The setting exists only in stacks with ingress, the only ones that
    # show this page; read by name so the module imports everywhere.
    base = str(getattr(settings, "traefik_api_url_effective"))
    async with httpx.AsyncClient(
        timeout=settings.HEALTH_CHECK_TIMEOUT_SECONDS
    ) as client:
        replies = await asyncio.gather(
            *(client.get(f"{base}{path}") for path in ENDPOINTS.values())
        )
    for reply in replies:
        reply.raise_for_status()
    return {key: reply.json() for key, reply in zip(ENDPOINTS, replies, strict=True)}


async def load() -> dict[str, Any]:
    """Traefik's configuration, or why it could not be read."""
    try:
        return {"error": None, **await fetch_traefik()}
    except Exception as exc:  # noqa: BLE001 - shown on the page, logged here
        logger.warning("Traefik API read failed", error=str(exc))
        return {"error": str(exc)}


def middleware_effect(middleware: dict[str, Any]) -> tuple[str, str] | None:
    """What a middleware does in effect, when that differs from "enabled":
    an allowlist open to every address guards nothing."""
    ranges = (middleware.get("ipAllowList") or {}).get("sourceRange") or []
    if middleware.get("type") == "ipallowlist" and OPEN_RANGES & set(ranges):
        return ("allows all", "warn")
    return None


def router_effect(
    router: dict[str, Any], middlewares: dict[str, dict[str, Any]]
) -> tuple[str, str] | None:
    """Traefik's own API or dashboard reachable with no auth in front."""
    if router.get("service") not in ADMIN_SERVICES:
        return None
    types = {middlewares.get(m, {}).get("type") for m in router.get("middlewares", [])}
    return None if types & AUTH_TYPES else ("no auth", "warn")


def short(name: str) -> str:
    """A Traefik name without its ``@provider`` suffix."""
    return name.split("@", 1)[0]


def _service_of(router: dict[str, Any]) -> str:
    """A router's service by its full name: routers may leave the provider
    off, services never do."""
    service = str(router.get("service", ""))
    return service if "@" in service else f"{service}@{router.get('provider', '')}"


def _servers(service: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not service:
        return []
    status = service.get("serverStatus") or {}
    return [
        {
            "url": server.get("url", ""),
            "state": status_cell(
                status.get(server.get("url"), "UNKNOWN"),
                _SERVER_TONES.get(status.get(server.get("url"), ""), "muted"),
            ),
        }
        for server in (service.get("loadBalancer") or {}).get("servers", [])
    ]


def _settings(middleware: dict[str, Any]) -> str:
    """A middleware's settings in words: ``attempts 5, initialInterval 2s``."""
    parts = []
    for key, value in middleware.items():
        if key in _MIDDLEWARE_META or not isinstance(value, dict):
            continue
        for name, setting in value.items():
            shown = (
                ", ".join(map(str, setting)) if isinstance(setting, list) else setting
            )
            parts.append(f"{name} {shown}")
    return "; ".join(parts)


def _middleware_step(
    name: str, middlewares: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    effect = middleware_effect(middlewares.get(name, {}))
    return {
        "label": short(name),
        "detail": f"Middleware, {effect[0]}" if effect else "Middleware",
        "tone": effect[1] if effect else None,
    }


def flows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """For each of the app's routers, the path a request takes."""
    services = {s["name"]: s for s in data.get("services", [])}
    middlewares = {m["name"]: m for m in data.get("middlewares", [])}
    return [
        {
            "name": short(router["name"]),
            "steps": [
                {
                    "label": ", ".join(router.get("entryPoints", [])),
                    "detail": "Entrypoint",
                },
                {"label": router.get("rule", ""), "detail": "Router"},
                *[
                    _middleware_step(m, middlewares)
                    for m in router.get("middlewares", [])
                ],
                {"label": short(_service_of(router)), "detail": "Service"},
                *[
                    {"label": s["url"], "detail": "Server"}
                    for s in _servers(services.get(_service_of(router)))
                ],
            ],
        }
        for router in data.get("routers", [])
        if router.get("provider") != "internal"
    ]


def _figures(data: dict[str, Any]) -> list[dict[str, Any]]:
    version = data.get("version") or {}
    return [
        {"label": "Routers", "value": len(data.get("routers", []))},
        {"label": "Services", "value": len(data.get("services", []))},
        {"label": "Middlewares", "value": len(data.get("middlewares", []))},
        {
            "label": "Entrypoints",
            "value": len(data.get("entrypoints", [])),
            "caption": f"Traefik {version.get('Version', '')}".strip(),
        },
    ]


def _state(item: dict[str, Any]) -> dict[str, str]:
    """What Traefik reports: is it running. Posture is ``_named``'s job."""
    status = str(item.get("status", ""))
    return status_cell(status or "unknown", "ok" if status == "enabled" else "warn")


def _named(name: str, effect: tuple[str, str] | None) -> dict[str, Any]:
    """A name and its posture warnings ("no auth", "allows all"): whether
    it should run like this, beside the status that says it runs."""
    return {"label": short(name), "warnings": [status_cell(*effect)] if effect else []}


def _priority(router: dict[str, Any]) -> str:
    priority = int(router.get("priority") or 0)
    return "Highest" if priority >= HIGHEST_PRIORITY else str(priority)


def _by_name(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sorted by the name shown, without the ``@provider`` suffix."""
    return sorted(items, key=lambda item: short(str(item.get("name", ""))))


def router_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Routers per entrypoint in the order Traefik tries them: highest
    priority first (by default, the longest rule)."""
    middlewares = {m["name"]: m for m in data.get("middlewares", [])}
    ordered = sorted(
        data.get("routers", []),
        key=lambda r: (
            ",".join(r.get("entryPoints", [])),
            -int(r.get("priority") or 0),
        ),
    )
    return [
        {
            "name": _named(r["name"], router_effect(r, middlewares)),
            "rule": r.get("rule", ""),
            "priority": _priority(r),
            "service": short(_service_of(r)),
            "middlewares": ", ".join(short(m) for m in r.get("middlewares", []))
            or None,
            "entrypoints": ", ".join(r.get("entryPoints", [])),
            "tls": "Yes" if r.get("tls") is not None else "No",
            "provider": r.get("provider", ""),
            "state": _state(r),
        }
        for r in ordered
    ]


def service_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": short(s["name"]),
            "servers": _servers(s),
            "used_by": ", ".join(short(r) for r in s.get("usedBy", [])) or None,
            "provider": s.get("provider", ""),
            "state": _state(s),
        }
        for s in _by_name(data.get("services", []))
    ]


def middleware_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": _named(m["name"], middleware_effect(m)),
            "type": m.get("type", ""),
            "settings": _settings(m) or None,
            "used_by": ", ".join(short(r) for r in m.get("usedBy", [])) or None,
            "state": _state(m),
        }
        for m in _by_name(data.get("middlewares", []))
    ]


async def section_context(
    section: str, ingress: ComponentStatus, req: SectionRequest
) -> dict[str, Any]:
    """Every section reads Traefik live; each shows its own slice."""
    data = await load()
    if data["error"]:
        return {"error": data["error"]}
    if section == "overview":
        return {
            "figures": _figures(data),
            "flows": flows(data),
            "entrypoints": [
                (e["name"], e.get("address", "")) for e in data.get("entrypoints", [])
            ],
        }
    rows = {
        "routers": router_rows,
        "services": service_rows,
        "middlewares": middleware_rows,
    }
    return {"error": None, "rows": rows[section](data)}
