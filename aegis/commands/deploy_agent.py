"""
``aegis deploy-agent``: the host runner behind the Overseer's deploy actions.

The app cannot deploy itself: the aegis CLI and the SSH key are on the
developer's machine, not in its container. So the
Overseer queues a request on the project's own Redis and this command, run
on that machine in the project directory, takes it: one at a time, through
the same ``aegis deploy-*`` commands a person would type, their output
streamed into the request's job (``jobs:<id>``, the app's ``RedisJobStore``
record) for the page to show.

The protocol (key names, the actions, each argument's pattern, the check
a request must pass) has one home, ``app/components/deploy/protocol.py``
in the project template; this loads it out of the template shipped in
this package, as the provider table is read.

A provider token comes with the request that needs it (the app's secret)
or from this process's environment; the request's wins. It reaches a
command only through the provider's environment variable, never its
arguments, is masked in every line sent, and is never written anywhere.
"""

import contextlib
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import redis
import typer

from .. import __version__
from ..cli import brand
from ..cli.validation import validate_copier_project
from ..core.component_files import PROJECT_SLUG_PLACEHOLDER, get_template_path
from ..core.footprint import DockerError, measure
from ..core.provision.http import ProvisionError, json_requester, mask_token
from ..core.provision.registry import PROVIDERS
from ..core.template_cleanup import env_value
from ..i18n import lazy_t, t
from .deploy import _get_project_root, _load_deploy_config
from .deploy_provision import CLOUDFLARE_TOKEN_ENV

_SPEC = importlib.util.spec_from_file_location(
    "aegis_deploy_protocol",
    get_template_path()
    / PROJECT_SLUG_PLACEHOLDER
    / "app"
    / "components"
    / "deploy"
    / "protocol.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_protocol = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_protocol)
PROTOCOL: dict[str, Any] = _protocol.PROTOCOL
RefusedError = _protocol.RefusedError
checked_token = _protocol.checked_token
# The app's job record (``RedisJobStore``): its key prefix and lifetime.
JOB_PREFIX = "jobs:"
JOB_KEEP_SECONDS = 6 * 3600
TAIL = 40  # lines of a command's output a job keeps for the page
JOB_ID = re.compile(r"[0-9a-f]{32}")  # a uuid4's hex, as the app mints them
AEGIS = [sys.executable, "-m", "aegis"]
DEFAULT_REDIS_PORT = "6379"
POLL_SECONDS = 1  # how long one BLPOP blocks, so a stop is noticed promptly
REDIS_RETRY_SECONDS = 2  # between tries while Redis is down


def validate(action: Any, args: Any) -> dict[str, str]:
    """The protocol's check (``protocol.validate``), and a provider this
    package can provision on."""
    given = _protocol.validate(action, args)
    if "provider" in given and given["provider"] not in PROVIDERS:
        supported = ", ".join(PROVIDERS)
        raise RefusedError(
            t(
                "provision.unknown_provider",
                provider=given["provider"],
                supported=supported,
            )
        )
    return given


def redis_url(root: Path) -> str:
    """Where the project's Redis answers on this machine, found the way the
    app's own host-side settings find it: ``REDIS_URL_LOCAL``, else
    ``REDIS_URL``'s database on the published port (``.env.ports``, which
    ``make serve`` writes). The environment wins, then ``.env.ports``, then
    ``.env``."""

    def setting(key: str) -> str | None:
        return (
            os.environ.get(key)
            or env_value(root / ".env.ports", key)
            or env_value(root / ".env", key)
        )

    if local := setting("REDIS_URL_LOCAL"):
        return local
    port = setting("REDIS_HOST_PORT") or DEFAULT_REDIS_PORT
    return f"redis://127.0.0.1:{port}{urlsplit(setting('REDIS_URL') or '').path}"


def presence() -> dict[str, Any]:
    """The heartbeat: who is listening, and the providers it holds tokens for
    (their names only)."""
    return {
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat(),
        "version": __version__,
        "providers": [
            key
            for key, p in PROVIDERS.items()
            if os.environ.get(p.token_env, "").strip()
        ],
    }


def _tokens() -> list[str]:
    """Every token this process holds, to mask wherever one would be sent."""
    names = [p.token_env for p in PROVIDERS.values()] + [CLOUDFLARE_TOKEN_ENV]
    return [value for name in names if (value := os.environ.get(name, "").strip())]


class Job:
    """One request's job record, written the way the app's store writes it."""

    def __init__(self, client: Any, job_id: str) -> None:
        self.client = client
        self.key = f"{JOB_PREFIX}{job_id}"
        self.lines: list[str] = []

    def _write(self, **fields: str) -> None:
        self.client.hset(self.key, mapping=fields)
        self.client.expire(self.key, JOB_KEEP_SECONDS)

    def line(self, text: str) -> None:
        """A line of output: the job's label, and the tail the page shows."""
        self.lines = [*self.lines, text][-TAIL:]
        self._write(label=text, result=json.dumps({"lines": self.lines}))

    def done(self, result: dict[str, Any]) -> None:
        self._write(status="done", result=json.dumps({"lines": self.lines} | result))

    def fail(self, error: str) -> None:
        self._write(
            status="failed", error=error, result=json.dumps({"lines": self.lines})
        )


def run(
    job: Job,
    root: Path,
    command: list[str],
    args: dict[str, str],
    env: dict[str, str] | None = None,
) -> int:
    """``aegis <command>`` on the project, each argument its own ``--flag``
    (never through a shell), ``env`` (a request's token) added to its
    environment, its output streamed into ``job``. Its exit code."""
    env = env or {}
    argv = [*AEGIS, command[0], "--project-path", str(root), *command[1:]]
    for key, value in args.items():
        argv += [f"--{key}", value]
    tokens = [*env.values(), *_tokens()]
    with subprocess.Popen(
        argv,
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        env=os.environ | env | {"PYTHONUNBUFFERED": "1"},
    ) as process:
        for raw in process.stdout or ():
            line = raw.rstrip()
            for token in tokens:
                line = line.replace(token, mask_token(token))
            if line:
                job.line(line)
        return process.wait()


def _ask(provider: str, env: dict[str, str], call: Callable[[Any], Any]) -> Any:
    """``call`` on the provider's client, with the request's token
    (``env``) or this process's; a provider's refusal says why."""
    spec = PROVIDERS[provider]
    token = env.get(spec.token_env) or os.environ.get(spec.token_env, "").strip()
    if not token:
        raise RefusedError(t("provision.token_missing", env=spec.token_env))
    try:
        return call(spec.client(json_requester(spec.api_url, token)))
    except ProvisionError as exc:  # its message never carries the token
        raise RefusedError(str(exc)) from None


def quote(args: dict[str, str], env: dict[str, str]) -> str:
    """The provider's monthly price for the size and region now."""
    return _ask(
        args["provider"], env, lambda c: c.monthly_price(args["size"], args["region"])
    )


def catalog(provider: str, env: dict[str, str]) -> dict[str, Any]:
    """What the provider sells where (its client's ``catalog``), in its
    currency."""
    found = _ask(provider, env, lambda c: c.catalog())
    return found | {"currency": PROVIDERS[provider].currency}


def _fresh(at: Any) -> None:
    """Refuse a request older than the protocol allows: whoever asked has
    likely moved on, and a deploy should not land unannounced."""
    try:
        sent = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        raise RefusedError(t("deploy_agent.unreadable")) from None
    age = datetime.now(UTC) - sent.replace(tzinfo=sent.tzinfo or UTC)
    if age.total_seconds() > PROTOCOL["stale_seconds"]:
        minutes = int(age.total_seconds() // 60)
        raise RefusedError(t("deploy_agent.stale", minutes=minutes))


def _token_env(
    root: Path, action: str, args: dict[str, str], token: str | None
) -> dict[str, str]:
    """The request's token under its provider's variable (the provider it
    names, else the provisioned server's); empty when it brought none."""
    if token is None:
        return {}
    record = (_load_deploy_config(str(root)) or {}).get("provision") or {}
    key = _protocol.token_provider(action, args, record)
    if key not in PROVIDERS:
        raise RefusedError(t("deploy_agent.no_provider"))
    return {PROVIDERS[key].token_env: token}


def _execute(
    job: Job, root: Path, action: str, args: dict[str, str], token: str | None
) -> None:
    env = _token_env(root, action, args, token)
    if action == "footprint":
        try:
            found = json.dumps(measure(root))
        except DockerError as exc:
            raise RefusedError(str(exc)) from None
        job.client.set(PROTOCOL["footprint"], found, ex=PROTOCOL["footprint_seconds"])
        job.done({})
        return
    if action == "catalog":
        key = f"{PROTOCOL['catalog']}{args['provider']}"
        found = json.dumps(catalog(args["provider"], env))
        job.client.set(key, found, ex=PROTOCOL["catalog_seconds"])
        job.done({})
        return
    if action == "provision":
        # The price confirmed in the Overseer, asked again before anything
        # is created; checked here, so it is not one of the command's flags.
        confirmed = args.pop("price")
        if (price := quote(args, env)) != confirmed:
            raise RefusedError(
                t("deploy_agent.price_changed", price=price, confirmed=confirmed)
            )
    command = PROTOCOL["actions"][action]["command"]
    if code := run(job, root, command, args, env):
        raise RefusedError(
            t("deploy_agent.command_failed", command=f"aegis {command[0]}", code=code)
        )
    job.done({"exit_code": 0})


def handle(client: Any, root: Path, raw: str) -> None:
    """Run one request and finish its job, done or failed with the reason."""
    try:
        request = json.loads(raw)
        job_id = request["job_id"]
    except (ValueError, TypeError, KeyError):
        brand.warn(t("deploy_agent.unreadable"))
        return
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        brand.warn(t("deploy_agent.unreadable"))
        return
    job = Job(client, job_id)
    action = request.get("action")
    typer.echo(t("deploy_agent.request", action=action, by=request.get("by") or "?"))
    try:
        _fresh(request.get("at"))
        args = validate(action, request.get("args"))
        token = checked_token(action, request.get("token"))
        _execute(job, root, action, args, token)
    except RefusedError as exc:
        job.fail(str(exc))
        brand.warn(str(exc))
        return
    except KeyboardInterrupt:
        job.fail(t("deploy_agent.stopped"))
        raise
    brand.success(t("deploy_agent.done", action=action))


def serve(client: Any, root: Path, stop: threading.Event | None = None) -> None:
    """Take requests until ``stop`` is set, beating the whole time so the
    Overseer knows someone is listening; the heartbeat goes when this does."""
    stop = stop or threading.Event()
    key, every = PROTOCOL["heartbeat"], PROTOCOL["beat_seconds"]
    beat = json.dumps(presence())
    stopped = threading.Event()

    def beating() -> None:
        while not stopped.wait(every):
            with contextlib.suppress(redis.RedisError):
                client.set(key, beat, ex=every * 3)

    client.set(key, beat, ex=every * 3)
    thread = threading.Thread(target=beating, daemon=True)
    thread.start()
    try:
        while not stop.is_set():
            try:
                item = client.blpop([PROTOCOL["requests"]], timeout=POLL_SECONDS)
            except redis.RedisError:
                # The stack restarting; listen again once Redis is back.
                stop.wait(REDIS_RETRY_SECONDS)
                continue
            if item:
                handle(client, root, item[1])
    finally:
        stopped.set()
        thread.join()
        with contextlib.suppress(redis.RedisError):
            client.delete(key)


def wait_for_redis(
    client: Any, url: str, sleep: Callable[[float], None] = time.sleep
) -> None:
    """Until the project's Redis answers. Started beside the stack (``make
    serve``), the agent is usually up first; it says where it waits once."""
    said = False
    while True:
        try:
            client.ping()
            return
        except redis.RedisError as exc:
            if not said:
                typer.echo(t("deploy_agent.no_redis", url=url, error=exc))
                said = True
            sleep(REDIS_RETRY_SECONDS)


def deploy_agent_command(
    project_path: str | None = typer.Option(
        None, "--project-path", help=lazy_t("common.help_project_path")
    ),
) -> None:
    """
    Run the Overseer's deploy requests on this machine.

    Listens on the project's Redis for what Overseer > Deployments asks for
    (a provider's sizes and regions, a new server, a deploy, a backup, a
    rollback, a destroy) and runs it with the aegis deploy commands, one at
    a time, with your SSH key: run it where that is, with the stack up. A cloud token comes with
    the request (Overseer > Secrets) or from this shell's environment.

    Examples:
        - aegis deploy-agent
    """
    root = _get_project_root(project_path).resolve()
    validate_copier_project(root, "deploy-agent")
    url = redis_url(root)
    client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=10)
    try:
        wait_for_redis(client, url)
    except KeyboardInterrupt:
        typer.echo(t("deploy_agent.stopping"))
        return
    providers = ", ".join(presence()["providers"]) or "-"
    brand.success(t("deploy_agent.listening", url=url, providers=providers))
    try:
        serve(client, root)
    except KeyboardInterrupt:
        typer.echo(t("deploy_agent.stopping"))
