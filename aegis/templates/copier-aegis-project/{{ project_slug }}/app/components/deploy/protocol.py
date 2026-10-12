"""The deploy agent's protocol: the Redis keys, the actions it runs and
each argument's pattern, and the one check a request must pass.

The app (``agent.py``) checks a request before queueing it and ``aegis
deploy-agent`` checks it again before running it; both use this module,
which the CLI loads out of the template it ships. So it imports nothing
but the standard library.
"""

import re
from typing import Any

PROTOCOL: dict[str, Any] = {
    "requests": "deploy:requests",
    "heartbeat": "deploy:agent",
    "last": "deploy:last",
    "beat_seconds": 10,
    "stale_seconds": 300,
    "args": {
        "provider": "[a-z0-9][a-z0-9-]{0,31}",
        "size": "[a-z0-9][a-z0-9-]{0,39}",
        "region": "[a-z0-9][a-z0-9-]{0,31}",
        "domain": r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
        "email": r"[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@(?:[A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}",
        "price": r"\d{1,6}\.\d{2}",
        "backup": r"\d{4}-\d{2}-\d{2}_\d{6}",
        "confirm": "[a-z0-9][a-z0-9-]{0,62}",
    },
    "actions": {
        "quote": {
            "required": ["provider", "size", "region"],
            "optional": ["domain", "email"],
        },
        "provision": {
            "command": ["deploy-provision", "--yes"],
            "required": ["provider", "size", "region", "price"],
            "optional": ["domain", "email"],
        },
        "deploy": {
            "command": ["deploy"],
        },
        "backup": {
            "command": ["deploy-backup"],
        },
        "backups": {
            "command": ["deploy-backups"],
        },
        "rollback": {
            "command": ["deploy-rollback"],
            "optional": ["backup"],
        },
        "destroy": {
            "command": ["deploy-destroy"],
            "required": ["confirm"],
        },
    },
}


class RefusedError(ValueError):
    """A request that will not be run; the message says why."""


def validate(action: Any, args: Any) -> dict[str, str]:
    """``args`` without its empty values, if ``action`` takes exactly them
    and each matches its pattern; RefusedError otherwise."""
    spec = PROTOCOL["actions"].get(action) if isinstance(action, str) else None
    if spec is None or not isinstance(args, dict):
        raise RefusedError(f"Not an action the deploy agent runs: {action}")
    required = set(spec.get("required", ()))
    given = {k: v for k, v in args.items() if v not in (None, "")}
    wrong = (set(given) - required - set(spec.get("optional", ()))) | (
        required - set(given)
    )
    if wrong:
        names = ", ".join(sorted(map(str, wrong)))
        raise RefusedError(f"{action} refused: unexpected or missing {names}")
    for key, value in given.items():
        if not isinstance(value, str) or not re.fullmatch(PROTOCOL["args"][key], value):
            raise RefusedError(f"Refused: {key} is not a valid value.")
    return given
