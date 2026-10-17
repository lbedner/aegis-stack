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
import json
import os
import re
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import redis
import typer

from .. import __version__
from ..cli import brand
from ..cli.validation import validate_copier_project
from ..core.deploy_protocol import protocol as _protocol
from ..core.footprint import Docker, DockerError, measure, runner
from ..core.provision.http import ProvisionError, json_requester, mask_token
from ..core.provision.provider import monthly_price
from ..core.provision.registry import DNS_SECRETS, PROVIDERS
from ..core.template_cleanup import env_value
from ..i18n import lazy_t, t
from .deploy import (
    ACTOR_ENV,
    _get_project_root,
    _load_deploy_config,
    _run_remote_capture,
    app_deploy,
)
from .deploy_backup import list_backups
from .deploy_upload import server_missing

PROTOCOL: dict[str, Any] = _protocol.PROTOCOL
LOOKS = 4  # looks answered at once (a catalog, an account, the footprint)
RefusedError = _protocol.RefusedError
checked_token = _protocol.checked_token
# The app's job record (``RedisJobStore``): its key prefix and lifetime.
JOB_PREFIX = "jobs:"
JOB_KEEP_SECONDS = 6 * 3600
TAIL = 400  # lines of a command's output a job keeps (the page, Copy)
JOB_ID = re.compile(r"[0-9a-f]{32}")  # a uuid4's hex, as the app mints them
AEGIS = [sys.executable, "-m", "aegis"]
REDIS_PORT = "6379"  # the redis service's, inside the stack
POLL_SECONDS = (
    1  # how often a wait looks up (BLPOP, the parent), so a stop is noticed promptly
)
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


def redis_url(root: Path, docker: Docker | None = None) -> str:
    """Where the project's own Redis answers on this machine:
    ``REDIS_URL_LOCAL``, else ``REDIS_URL``'s database on the port Docker
    published for the ``redis`` container compose started from ``root``
    (its working-directory label, so neither the project's name nor
    another checkout of it can stand in). Asked each time, never read from
    ``.env.ports``: ports are handed out per run, so one written down may
    since be another project's Redis, whose requests would run here. The
    environment wins, then ``.env``. DockerError while none is running."""

    def setting(key: str) -> str | None:
        return os.environ.get(key) or env_value(root / ".env", key)

    if local := setting("REDIS_URL_LOCAL"):
        return local
    docker = docker or runner(root)
    found = docker(
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project.working_dir={root}",
        "--filter",
        "label=com.docker.compose.service=redis",
    ).split()
    if not found:
        raise DockerError("no redis container is running from it")
    address = docker("port", found[0], REDIS_PORT).split()[0]  # IPv4 first
    return f"redis://{address}{urlsplit(setting('REDIS_URL') or '').path}"


def presence(root: Path) -> dict[str, Any]:
    """The heartbeat: who is listening and in which checkout (``root``),
    the actions it runs (an app newer than it asks for one it lacks), and
    the providers it holds tokens for (their names only)."""
    return {
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "root": str(root),
        "started_at": datetime.now(UTC).isoformat(),
        "version": __version__,
        "actions": list(PROTOCOL["actions"]),
        "revision": PROTOCOL["revision"],
        "providers": [
            key
            for key, p in PROVIDERS.items()
            if os.environ.get(p.token_env, "").strip()
        ],
    }


def _tokens() -> list[str]:
    """Every token this process holds, to mask wherever one would be sent."""
    names = [p.token_env for p in PROVIDERS.values()] + sorted(DNS_SECRETS)
    return [value for name in names if (value := os.environ.get(name, "").strip())]


def _masked(text: str, tokens: list[str]) -> str:
    """``text`` with every one of ``tokens`` masked."""
    for token in tokens:
        text = text.replace(token, mask_token(token))
    return text


class Job:
    """One request's job record, written the way the app's store writes it."""

    def __init__(self, client: Any, job_id: str) -> None:
        self.client = client
        self.key = f"{JOB_PREFIX}{job_id}"
        self.lines: list[str] = []
        self.progress: Any = None

    def _write(self, **fields: str) -> None:
        # Redis restarting must not stop the command whose output this is
        # (its pipe closed, it would die part way); each write carries the
        # whole record, so the next one puts it right.
        with contextlib.suppress(redis.RedisError):
            self.client.hset(self.key, mapping=fields)
            self.client.expire(self.key, JOB_KEEP_SECONDS)

    def _result(self, **more: Any) -> str:
        return json.dumps({"lines": self.lines, "progress": self.progress} | more)

    def line(self, text: str) -> None:
        """A line of output: the job's label, and the tail the page shows;
        or, a ``progress_line``, where its steps stand."""
        if (progress := _protocol.read_progress(text)) is not None:
            self.progress = progress
            self._write(result=self._result())
            return
        self.lines = [*self.lines, text][-TAIL:]
        self._write(label=text, result=self._result())

    def done(self, result: dict[str, Any]) -> None:
        self._write(status="done", result=self._result(**result))

    def fail(self, error: str) -> None:
        self._write(status="failed", error=error, result=self._result())


def run(
    job: Job,
    root: Path,
    command: list[str],
    args: dict[str, str],
    env: dict[str, str] | None = None,
    action: str = "",
) -> int:
    """``aegis <command>`` on the project, each argument its own ``--flag``
    (never through a shell), ``env`` (a request's token) added to its
    environment, its output streamed into ``job``; told it runs ``action``,
    whose step bar it marks. Its exit code."""
    env = env or {}
    argv = [*AEGIS, command[0], "--project-path", str(root), *command[1:]]
    for key, value in args.items():
        argv += [f"--{key}", value]
    # Every value handed in is a secret but who asked (``ACTOR_ENV``).
    tokens = [v for k, v in env.items() if k != ACTOR_ENV] + _tokens()
    with subprocess.Popen(
        argv,
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        env=os.environ
        | env
        | {"PYTHONUNBUFFERED": "1", PROTOCOL["progress_env"]: action},
    ) as process:
        for raw in process.stdout or ():
            line = _masked(raw.rstrip(), tokens)
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
        args["provider"], env, lambda c: monthly_price(c, args["size"], args["region"])
    )


def _found(
    root: Path, action: str, args: dict[str, str], env: dict[str, str]
) -> dict[str, Any]:
    """What a ``kept`` action answers: a provider's catalog or account (in
    its currency), or the stack's footprint (``aegis.core.footprint``); a
    refusal says why not."""
    if action in ("catalog", "account"):  # the client's method of that name
        provider = args["provider"]
        found = _ask(provider, env, lambda c: getattr(c, action)())
        return found | {"currency": PROVIDERS[provider].currency}
    if action in ("backups", "history", "storage"):  # read on the server
        server = (_load_deploy_config(str(root)) or {}).get("server")
        if not server:
            raise RefusedError(t("deploy.no_config"))
        remote = partial(_run_remote_capture, server["host"], server["user"])
        if action == "backups":
            return {"backups": list_backups(remote, server["path"])}
        if action == "storage":
            return {"missing": _missing(remote, server["path"])}
        return {
            "deploys": _history(root, remote, server["path"]),
            "events": _events(root, remote, server["path"]),
        }
    try:
        return measure(root)
    except DockerError as exc:
        raise RefusedError(str(exc)) from None


def _missing(remote: Any, deploy_path: str) -> list[str]:
    """The stored files the server's rows name and its store lacks."""
    missing = server_missing(remote, deploy_path)
    if missing is None:
        raise RefusedError(t("deploy.storage_cannot_check"))
    return missing


def _events(root: Path, remote: Any, deploy_path: str) -> list[dict[str, Any]]:
    """Everything else done to the server, newest first: the last line of
    its ``deploy events``; none from a project without them."""
    result = app_deploy(root, remote, deploy_path, "events")
    lines = (result.stdout or "").strip().splitlines() if result else []
    if result is None or result.returncode != 0 or not lines:
        return []
    return json.loads(lines[-1])


def _history(root: Path, remote: Any, deploy_path: str) -> list[dict[str, Any]]:
    """The server's deploy history, newest first: the last line its
    ``deploy history`` prints (the JSON, whatever the app logged before)."""
    result = app_deploy(root, remote, deploy_path, "history")
    if result is None:
        raise RefusedError(t("deploy_agent.no_history"))
    lines = result.stdout.strip().splitlines()
    if result.returncode != 0 or not lines:
        raise RefusedError(result.stderr.strip() or f"exit {result.returncode}")
    return json.loads(lines[-1])


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


def _dns_env(action: str, keys: Any) -> dict[str, str]:
    """A request's DNS keys, each under the variable a DNS provider reads
    (``DNS_PROVIDERS``); any other name (``PATH``, ``LD_PRELOAD``) would
    change what the command runs, so it is refused."""
    keys = _protocol.checked_dns_keys(action, keys)
    if not set(keys) <= DNS_SECRETS:
        raise RefusedError("Refused: the DNS keys are not a DNS provider's.")
    return keys


def _execute(
    job: Job,
    root: Path,
    action: str,
    args: dict[str, str],
    token: str | None,
    dns: dict[str, str],
) -> None:
    env = _token_env(root, action, args, token) | dns
    spec = PROTOCOL["actions"][action]
    if _protocol.is_kept(action):
        key = _protocol.kept_key(action, args)
        if not job.client.exists(key):  # asked twice, found once
            found = _found(root, action, args, env)
            job.client.set(key, json.dumps(found), ex=spec["seconds"])
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
    command = spec["command"]
    code = run(job, root, command, args, env, action)
    # What a command may have changed (the backups, the history) is looked
    # at again.
    job.client.delete(
        *(
            _protocol.kept_key(name, {})
            for name, kept in PROTOCOL["actions"].items()
            if kept.get("until_a_command")
        )
    )
    if spec.get("token"):  # it may have changed what the account runs
        for key in PROVIDERS:
            job.client.delete(_protocol.kept_key("account", {"provider": key}))
    if code:
        raise RefusedError(
            t("deploy_agent.command_failed", command=f"aegis {command[0]}", code=code)
        )
    job.done({"exit_code": 0})


def _request(raw: str) -> dict[str, Any] | None:
    """A request off the queue, None (said) for one without a job to
    answer in."""
    try:
        request = json.loads(raw)
        job_id = request["job_id"]
    except (ValueError, TypeError, KeyError):
        job_id = None
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        brand.warn(t("deploy_agent.unreadable"))
        return None
    return request


def handle(client: Any, root: Path, request: dict[str, Any]) -> None:
    """Run one request and finish its job, done or failed with the reason."""
    job = Job(client, request["job_id"])
    action = cast(str, request.get("action"))  # checked by validate, below
    typer.echo(t("deploy_agent.request", action=action, by=request.get("by") or "?"))
    try:
        _fresh(request.get("at"))
        args = validate(action, request.get("args"))
        token = checked_token(action, request.get("token"))
        # Who asked, for the event the command records (``recorded``).
        extra = _dns_env(action, request.get("dns_keys")) | (
            {ACTOR_ENV: str(request["by"])} if request.get("by") else {}
        )
        _execute(job, root, action, args, token, extra)
    except RefusedError as exc:
        job.fail(str(exc))
        brand.warn(str(exc))
        return
    except KeyboardInterrupt:
        job.fail(t("deploy_agent.stopped"))
        raise
    except Exception as exc:  # noqa: BLE001 - this job's failure, not the agent's
        error = _masked(f"{type(exc).__name__}: {exc}", _tokens())
        job.fail(error)
        brand.warn(error)
        return
    brand.success(t("deploy_agent.done", action=action))


def _reap(client: Any) -> None:
    """Deploy jobs left running by an agent that stopped part way fail
    saying so: one agent serves a project, so no one is running them, and
    the page would wait on them (its buttons, a list) until they expired.
    Not one whose request still waits on the queue: that is about to run."""
    queued = " ".join(client.lrange(PROTOCOL["requests"], 0, -1))
    for key in client.scan_iter(match=f"{JOB_PREFIX}*"):
        found = client.hgetall(key)
        job_id = key.removeprefix(JOB_PREFIX)
        mine = found.get("name", "").startswith("deploy:")
        if mine and found.get("status") == "running" and job_id not in queued:
            Job(client, job_id).fail(t("deploy_agent.stopped"))


def _alive(held: dict[str, Any]) -> bool:
    """Whether the agent that left heartbeat ``held`` still runs; one on
    another machine is taken to."""
    if held.get("host") != socket.gethostname():
        return True
    try:
        os.kill(held["pid"], 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # alive, someone else's
        pass
    return True


def _claim(client: Any, beat: str) -> None:
    """The project's heartbeat taken (``beat``), in one step when it is
    free, so two agents finding Redis at once cannot both pass. Refused
    while another agent listens: two would take turns at its requests (two
    deploys at once), and each would fail the jobs the other runs
    (``_reap``). One killed without taking its heartbeat down does not
    count."""
    key, ttl = PROTOCOL["heartbeat"], PROTOCOL["beat_seconds"] * 3
    if client.set(key, beat, nx=True, ex=ttl):
        return
    held = json.loads(client.get(key) or "{}")
    if held.get("pid") not in (None, os.getpid()) and _alive(held):
        root = held.get("root", "?")
        raise RefusedError(t("deploy_agent.another", pid=held["pid"], root=root))
    client.set(key, beat, ex=ttl)


def serve(client: Any, root: Path, stop: threading.Event) -> None:
    """Take requests until ``stop`` is set or Redis goes away, beating the
    whole time so the Overseer knows someone is listening; the heartbeat
    goes when this does."""
    key, every = PROTOCOL["heartbeat"], PROTOCOL["beat_seconds"]
    beat = json.dumps(presence(root))
    stopped = threading.Event()

    def beating() -> None:
        while not stopped.wait(every):
            with contextlib.suppress(redis.RedisError):
                client.set(key, beat, ex=every * 3)

    _reap(client)
    client.set(key, beat, ex=every * 3)
    thread = threading.Thread(target=beating, daemon=True)
    thread.start()
    commands, looks = ThreadPoolExecutor(1), ThreadPoolExecutor(LOOKS)
    try:
        while not stop.is_set():
            try:
                item = client.blpop([PROTOCOL["requests"]], timeout=POLL_SECONDS)
                if item and (request := _request(item[1])):
                    # Commands one at a time, in order; a look (read only,
                    # quick) beside them, never queued behind a server being
                    # made until too old to run.
                    look = _protocol.is_kept(request.get("action"))
                    (looks if look else commands).submit(handle, client, root, request)
            except redis.RedisError:
                # The stack stopping or restarting: found again (``listen``),
                # on whatever port it comes back on.
                return
    except BaseException:
        # Interrupted: a command not started yet does not start.
        # ponytail: its job says it waits until it expires (hours); put it
        # back on the queue if that ever matters.
        commands.shutdown(cancel_futures=True)
        raise
    finally:
        # What was taken off the queue is finished before leaving.
        commands.shutdown()
        looks.shutdown()
        stopped.set()
        thread.join()
        with contextlib.suppress(redis.RedisError):
            client.delete(key)


def connect(root: Path, stop: threading.Event) -> Any:
    """A client on the project's own Redis once it answers, where it is
    asked again each try (the stack may come up on another port); None if
    ``stop`` is set first. Started beside the stack (``make serve``), the
    agent is usually up first; it says why it waits once. Refused beside
    another agent (``_claim``), each time it finds Redis again."""
    said = False
    while not stop.is_set():
        url = str(root)
        try:
            url = redis_url(root)
            client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=10)
            client.ping()
            _claim(client, json.dumps(presence(root)))
        except (DockerError, redis.RedisError) as exc:
            if not said:
                typer.echo(t("deploy_agent.no_redis", url=url, error=exc))
                said = True
            stop.wait(REDIS_RETRY_SECONDS)
            continue
        providers = ", ".join(presence(root)["providers"]) or "-"
        brand.success(t("deploy_agent.listening", url=url, providers=providers))
        return client
    return None


def listen(root: Path, stop: threading.Event) -> None:
    """Serve the project's Redis whenever it is up, until ``stop``."""
    while (client := connect(root, stop)) is not None:
        # Gone again while starting (its jobs reaped, its heartbeat set):
        # found again, as when it goes between requests.
        with contextlib.suppress(redis.RedisError):
            serve(client, root, stop)


def watch_parent(stop: threading.Event) -> None:
    """Set ``stop`` once whoever started this agent (make serve, a shell)
    is gone: left behind, it would listen for a stack nobody runs, and
    stand beside the next make serve's agent."""
    parent = os.getppid()

    def watch() -> None:
        while not stop.wait(POLL_SECONDS):
            if os.getppid() != parent:
                stop.set()

    threading.Thread(target=watch, daemon=True).start()


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
    stop = threading.Event()
    watch_parent(stop)
    try:
        listen(root, stop)
    except RefusedError as exc:
        brand.error(str(exc), err=True)
        raise typer.Exit(1) from None
    except KeyboardInterrupt:
        pass
    typer.echo(t("deploy_agent.stopping"))
