"""Whether a server size has room for the stack: its production services'
memory (in use now, and their limits), CPU limits and disk (images and
data), against what the size offers less what the system takes. Each a
row the Overseer draws as a bar, toned (``ok``, ``warn``, ``error``) and
saying why. CPU limits past the server's cores are said (``muted``), not
counted: busy services share them, and nothing runs out. From the agent's measurement (``aegis.core.footprint``) and a
size from the provider's catalog. No UI framework imports.
"""

from typing import Any

from app.core.formatting import format_bytes

MIB = 1024**2
GIB = 1024**3
# What a small server's own system (Ubuntu, Docker) takes before the stack.
SYSTEM_MEMORY = 400 * MIB
SYSTEM_DISK = 5 * GIB
DISK_TIGHT = 0.8  # of the free disk, past which there is little room to grow
VERDICTS = {
    "ok": "It fits.",
    "warn": "It fits, with little to spare.",
    "error": "Too small.",
}


def _bar(value: float | None, scale: float) -> float | None:
    """``value`` as a percentage of the bar's ``scale``."""
    return None if value is None else round(100 * value / scale, 1)


def _row(
    key: str,
    label: str,
    tone: str,
    why: str,
    figures: str,
    scale: float,
    **marks: float | None,
) -> dict[str, Any]:
    """A bar: ``solid`` (in use), ``dashed`` (the limits), ``line`` (the
    server), each a percentage of ``scale``; the limits may come as
    ``segments`` instead, one per service."""
    bars = {
        name: _bar(marks.get(name), scale or 1) for name in ("solid", "dashed", "line")
    }
    return {
        "key": key,
        "label": label,
        "tone": tone,
        "why": why,
        "figures": figures,
    } | bars


def _segments(ceilings: list[tuple[str, int]], scale: float) -> list[dict[str, Any]]:
    """Each service's limit as its own piece of the dashed outline, end to
    end from the left (``x``, ``width``: percentages of ``scale``)."""
    found, x = [], 0.0
    for name, ceiling in ceilings:
        width = _bar(ceiling, scale) or 0.0
        title = f"{name}: up to {format_bytes(ceiling)}"
        found.append({"name": name, "title": title, "x": round(x, 1), "width": width})
        x += width
    return found


def _memory(services: list[dict[str, Any]], size: dict[str, Any]) -> dict[str, Any]:
    room = size["memory_mb"] * MIB - SYSTEM_MEMORY
    used = sum(s["used"] or 0 for s in services)
    # Each service's ceiling, biggest first: its limit, or, without one,
    # what it uses (it can take that much, at the least); none, left out.
    named = ((s["name"], s["memory"] or s["used"] or 0) for s in services)
    ceilings = sorted(
        ((name, c) for name, c in named if c), key=lambda found: found[1], reverse=True
    )
    limits = sum(ceiling for _, ceiling in ceilings)
    if used > room:
        tone = "error"
        why = (
            f"The stack uses {format_bytes(used)} now; this server has "
            f"{format_bytes(room)} for it."
        )
    elif limits > room:
        named = " and ".join(f"{n} ({format_bytes(c)})" for n, c in ceilings[:2])
        tone = "warn"
        why = (
            f"Fits today ({format_bytes(used)} of {format_bytes(room)}). If every "
            f"service grew to its limit, together they would need "
            f"{format_bytes(limits)}; the biggest limits are {named}."
        )
    else:
        tone = "ok"
        why = (
            "Room to spare: even if every service grew to its limit, together "
            f"they would need {format_bytes(limits)} of {format_bytes(room)}."
        )
    figures = (
        f"{format_bytes(used)} in use · {format_bytes(limits)} limits · "
        f"{format_bytes(room)} on this server"
    )
    if unseen := [s["name"] for s in services if s["used"] is None]:
        figures += f" · not running here: {', '.join(unseen)}"
    scale = max(room, limits, used)
    row = _row("memory", "Memory", tone, why, figures, scale, solid=used, line=room)
    return row | {"segments": _segments(ceilings, scale or 1)}


def _cpu(services: list[dict[str, Any]], size: dict[str, Any]) -> dict[str, Any]:
    have = size["vcpus"]
    limits = round(sum(s["cpus"] or 0 for s in services), 2)
    over = [
        f"{s['name']} ({s['cpus']:g} CPUs)" for s in services if (s["cpus"] or 0) > have
    ]
    if over:
        # Docker refuses such a limit outright: the service never starts.
        tone = "error"
        why = (
            f"Docker will not start {', '.join(over)} on {have}: no one "
            "service may be limited to more CPUs than the server has."
        )
    elif limits > have:
        tone = "muted"
        why = (
            f"The limits add up to {limits:g} CPUs on {have}: when busy, the "
            "services share them, so it runs slower, not out."
        )
    else:
        tone = "ok"
        why = f"The limits ({limits:g} CPUs) fit in {have}."
    figures = f"{limits:g} CPUs of limits · {have} on this server"
    return _row(
        "cpu", "CPU", tone, why, figures, max(limits, have), dashed=limits, line=have
    )


def _disk(found: dict[str, Any], size: dict[str, Any]) -> dict[str, Any]:
    room = size["disk_gb"] * GIB - SYSTEM_DISK
    needed = found["images"] + found["data"]
    if needed > room:
        tone = "error"
        why = f"Images and data take {format_bytes(needed)}; this server has {format_bytes(room)}."
    elif needed > room * DISK_TIGHT:
        tone = "warn"
        why = f"Images and data take {format_bytes(needed)} of {format_bytes(room)}: little room to grow."
    else:
        tone = "ok"
        why = f"Images and data take {format_bytes(needed)} of {format_bytes(room)}."
    figures = f"{format_bytes(needed)} of images and data · {format_bytes(room)} on this server"
    return _row(
        "disk", "Disk", tone, why, figures, max(room, needed), solid=needed, line=room
    )


def fit(found: dict[str, Any], size: dict[str, Any]) -> dict[str, Any]:
    """Memory, CPU and disk for ``size`` (a catalog size: memory_mb, vcpus,
    disk_gb), and the worst of them as the ``verdict``."""
    rows = [
        _memory(found["services"], size),
        _cpu(found["services"], size),
        _disk(found, size),
    ]
    tones = {row["tone"] for row in rows}  # muted counts as fitting
    verdict = "error" if "error" in tones else "warn" if "warn" in tones else "ok"
    note = (
        "Solid: in use now, on this machine. Dashed: the services' limits in "
        "production. Line: this server, less about "
        f"{format_bytes(SYSTEM_MEMORY)} of memory and {format_bytes(SYSTEM_DISK)} "
        "of disk for its own system."
    )
    return {
        "rows": rows,
        "verdict": verdict,
        "headline": VERDICTS[verdict],
        "note": note,
    }
