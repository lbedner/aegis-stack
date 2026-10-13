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
    server), each a percentage of ``scale``."""
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


def _memory(services: list[dict[str, Any]], size: dict[str, Any]) -> dict[str, Any]:
    room = size["memory_mb"] * MIB - SYSTEM_MEMORY
    used = sum(s["used"] or 0 for s in services)
    # A service without a limit can take what it uses, at the least.
    limits = sum(s["memory"] or s["used"] or 0 for s in services)
    if used > room:
        tone = "error"
        why = (
            f"The stack uses {format_bytes(used)} now; this server has "
            f"{format_bytes(room)} for it."
        )
    elif limits > room:
        biggest = sorted(
            (s for s in services if s["memory"]),
            key=lambda s: s["memory"],
            reverse=True,
        )[:2]
        named = " and ".join(
            f"{s['name']} ({format_bytes(s['memory'])})" for s in biggest
        )
        tone = "warn"
        why = (
            f"Fits today ({format_bytes(used)} of {format_bytes(room)}), but the "
            f"limits add up to {format_bytes(limits)}: {named} could push it over."
        )
    else:
        tone = "ok"
        why = f"Room to spare: the limits ({format_bytes(limits)}) fit in {format_bytes(room)}."
    figures = (
        f"{format_bytes(used)} in use · {format_bytes(limits)} limits · "
        f"{format_bytes(room)} on this server"
    )
    if unseen := [s["name"] for s in services if s["used"] is None]:
        figures += f" · not running here: {', '.join(unseen)}"
    scale = max(room, limits, used)
    return _row(
        "memory",
        "Memory",
        tone,
        why,
        figures,
        scale,
        solid=used,
        dashed=limits,
        line=room,
    )


def _cpu(services: list[dict[str, Any]], size: dict[str, Any]) -> dict[str, Any]:
    have = size["vcpus"]
    limits = round(sum(s["cpus"] or 0 for s in services), 2)
    if limits > have:
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
    needed = found["images"] + sum(v["size"] for v in found["volumes"])
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
    return {"rows": rows, "verdict": verdict, "headline": VERDICTS[verdict]}
