"""The deploy agent's protocol: the Redis keys, the actions it runs and
each argument's pattern, and the one check a request must pass.

An action that ``kept`` answers rather than runs a command: the agent
keeps what it found under that key (``kept_key``) for ``seconds``, for the
Overseer to read (a provider's ``catalog``, what it sells where; its
``account``, what runs there now and what it has cost this month; the
stack's ``footprint``, what its production services take). It is asked
in the background: not the newest job the Overseer shows (``last``), and
never from its buttons. An action that acts on an account (``token``) and
runs a command changes what it runs, so the agent forgets the kept
``account`` after it.

An action marked ``token`` acts on a cloud provider's account (the one it
names, or the provisioned server's), and its request may carry the app's
token for it (``app.core.secrets``) as its own field, never in ``args``,
which are audited and echoed. The agent prefers it to its own environment's.

The app (``agent.py``) checks a request before queueing it and ``aegis
deploy-agent`` checks it again before running it; both use this module,
which the CLI loads out of the template it ships. So it imports nothing
but the standard library.
"""

import json
import re
from typing import Any

# A provision's steps, in order, as its step bar names them (``data``
# only when it was asked for).
PROVISION_STEPS = {
    "server": "Create the server",
    "boot": "First boot",
    "dns": "Point the name",
    "deploy": "Deploy",
    "data": "Bring my data",
}

# A backup's steps, as its step bar names them: those it takes, in the
# order it takes them (``database`` before ``files`` for SQLite, after for
# Postgres; ``offsite`` only for a server that pushes one).
BACKUP_STEPS = {
    "database": "Database",
    "files": "Code and settings",
    "documents": "Documents",
    "offsite": "Off the server",
}

PROTOCOL: dict[str, Any] = {
    "requests": "deploy:requests",
    "heartbeat": "deploy:agent",
    "last": "deploy:last",
    "beat_seconds": 10,
    "stale_seconds": 300,
    # Raised when a request carries something an older agent would drop
    # (2: a DNS provider's keys; 3: bringing this machine's data; 4: a
    # resume that refuses to start a new server; 5: the backups a rollback
    # is picked from): the heartbeat says which it speaks.
    "revision": 5,
    # Run by the agent (``progress_env`` set), a command with ``steps``
    # prints, as each starts, its plan and step (``progress_line``); the
    # agent keeps them in the job (``read_progress``) instead of its
    # output, and the Overseer draws the step bar from them.
    "progress": "::aegis-progress ",
    "progress_env": "AEGIS_PROGRESS",
    # A provider API token: its own characters only, so it can travel in an
    # environment variable and nothing else rides along with it.
    "token": r"[A-Za-z0-9._~+/=:-]{8,512}",
    "args": {
        "provider": "[a-z0-9][a-z0-9-]{0,31}",
        "size": "[a-z0-9][a-z0-9-]{0,39}",
        "region": "[a-z0-9][a-z0-9-]{0,31}",
        "domain": r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
        "dns": "[a-z0-9][a-z0-9-]{0,31}",
        # Who may reach the Overseer: networks, comma-separated (IPv4, IPv6).
        "allowlist": r"[0-9A-Fa-f.:]{2,39}/\d{1,3}(?:,[0-9A-Fa-f.:]{2,39}/\d{1,3}){0,15}",
        "email": r"[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@(?:[A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}",
        "price": r"\d{1,6}\.\d{2}",
        "backup": r"\d{4}-\d{2}-\d{2}_\d{6}",
        "confirm": "[a-z0-9][a-z0-9-]{0,62}",
        # Bring this machine's database to the new server (SQLite).
        "data": "local",
    },
    "actions": {
        "catalog": {
            "token": True,
            "required": ["provider"],
            "kept": "deploy:catalog:{provider}",
            "seconds": 3600,
        },
        "account": {
            "token": True,
            "required": ["provider"],
            "kept": "deploy:account:{provider}",
            "seconds": 300,
        },
        "footprint": {
            "kept": "deploy:footprint",
            "seconds": 600,
        },
        "provision": {
            "command": ["deploy-provision", "--yes"],
            "token": True,
            "dns": True,
            "required": ["provider", "size", "region", "price"],
            "optional": ["domain", "email", "dns", "allowlist", "data"],
            "steps": PROVISION_STEPS,
        },
        # A provision that stopped part way, carried on from its record in
        # ``.aegis/deploy.yml`` (its cloud, size, region, name and data);
        # refused by the command once there is none.
        "resume": {
            "command": ["deploy-provision", "--yes", "--resume"],
            "token": True,
            "dns": True,
            "steps": PROVISION_STEPS,
        },
        "deploy": {
            "command": ["deploy"],
        },
        "backup": {
            "command": ["deploy-backup"],
            "steps": BACKUP_STEPS,
        },
        # The server's backups (name, size, whether each holds the
        # database), so a rollback is picked from them, never typed;
        # forgotten by any command, which may have changed them.
        "backups": {
            "kept": "deploy:backups",
            "seconds": 600,
        },
        "rollback": {
            "command": ["deploy-rollback"],
            "required": ["backup"],
        },
        "destroy": {
            "command": ["deploy-destroy"],
            "token": True,
            "dns": True,
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


def checked_token(action: str, token: Any) -> str | None:
    """A request's provider token, None when it carries none; RefusedError
    for one ``action`` does not take, or anything but a token. The message
    never repeats it."""
    if token is None:
        return None
    if not PROTOCOL["actions"][action].get("token"):
        raise RefusedError(f"{action} refused: it takes no provider token.")
    if not isinstance(token, str) or not re.fullmatch(PROTOCOL["token"], token):
        raise RefusedError("Refused: the provider token is not a valid token.")
    return token


# A DNS key's variable name, as a provider table names them.
_KEY_NAME = r"[A-Z][A-Z0-9_]{2,63}"


def checked_dns_keys(action: str, keys: Any) -> dict[str, str]:
    """A request's DNS provider keys (``{variable: value}``), empty when it
    carries none; RefusedError for an action that takes none, or anything
    but names and tokens. Which names a DNS provider reads is the agent's
    to check (its provider table). The message never repeats a value."""
    if keys is None:
        return {}
    if not PROTOCOL["actions"][action].get("dns"):
        raise RefusedError(f"{action} refused: it takes no DNS keys.")
    if not isinstance(keys, dict) or not all(
        isinstance(name, str)
        and re.fullmatch(_KEY_NAME, name)
        and isinstance(value, str)
        and re.fullmatch(PROTOCOL["token"], value)
        for name, value in keys.items()
    ):
        raise RefusedError("Refused: the DNS keys are not valid keys.")
    return keys


def is_kept(action: Any) -> bool:
    """Whether ``action`` is one the agent ``kept`` answers (a look), not a
    command that changes anything."""
    return isinstance(action, str) and "kept" in PROTOCOL["actions"].get(action, {})


def progress_line(steps: list[str], at: str) -> str:
    """The line a command prints as its step ``at`` (of ``steps``) starts."""
    return PROTOCOL["progress"] + json.dumps({"steps": steps, "at": at})


def read_progress(line: str) -> dict[str, Any] | None:
    """Where a ``progress_line`` says the steps stand; None for any other
    line (or one cut short)."""
    if not line.startswith(PROTOCOL["progress"]):
        return None
    try:
        found = json.loads(line.removeprefix(PROTOCOL["progress"]))
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def kept_key(action: str, args: dict[str, str]) -> str:
    """Where the agent keeps what a ``kept`` action found."""
    return PROTOCOL["actions"][action]["kept"].format(**args)


def record_dns_provider(record: dict[str, Any]) -> str | None:
    """The DNS provider a provision record's name is at: where it was made
    (a record from before the provider was written down is Cloudflare's,
    the only one then), else where it is to be (``dns_provider``, so a
    resume brings its keys). None without a name of its own."""
    made = record.get("dns")
    if made:
        return made.get("provider") or "cloudflare"
    return record.get("dns_provider")


def token_provider(
    action: str, args: dict[str, str], record: dict[str, Any]
) -> str | None:
    """Whose token ``action`` needs: the provider it names, else the one
    the provisioned server is on (``record``, the provision record in
    ``.aegis/deploy.yml``); None for an action that needs none."""
    if not PROTOCOL["actions"][action].get("token"):
        return None
    return args.get("provider") or record.get("provider")
