"""What a cloud account already runs and costs, beside the server about to
be bought: its servers dearest first (aegis's own marked by the project
that made them), what they cost a month together and with the new one,
and what the account has spent this month where its provider says. From
the agent's look at the account (``aegis deploy-agent``'s ``account``). No
UI framework imports.
"""

from typing import Any

from app.core.formatting import format_relative_time


def cents(amount: str | None) -> int | None:
    """A provider's amount (``"24.00"``, whole units) in the minor units
    the ``money`` filter takes; None where it gave none."""
    return round(float(amount) * 100) if amount else None


def spend(found: dict[str, Any], price: str) -> dict[str, Any]:
    """``found`` (servers, month_to_date, missing, currency), its servers
    as table rows (_account.html's columns), with the monthly totals before
    and with a server at ``price``: every amount in cents."""
    servers = sorted(
        found["servers"], key=lambda s: cents(s["price"]) or 0, reverse=True
    )
    running = sum(cents(s["price"]) or 0 for s in servers)
    rows = [
        {
            "server": {"name": s["name"], "project": s["project"]},
            "size": s["size"],
            "region": s["region"],
            "price": cents(s["price"]),
            "currency": found["currency"],
            "age": format_relative_time(s["created"]),
        }
        for s in servers
    ]
    return {
        "servers": rows,
        "running": running,
        "with": running + (cents(price) or 0),
        "currency": found["currency"],
        "month_to_date": cents(found.get("month_to_date")),
        "missing": found.get("missing") or [],
    }
