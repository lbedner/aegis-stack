"""``aegis deploy-agent``: the host runner behind the Overseer's deploy actions.

No test reaches a real Redis, cloud or server: Redis is ``FakeRedis``, a
provider is a fake ``Requester``, and the ``aegis`` the agent runs is a
small script that prints its arguments.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import subprocess
import sys
import threading
import types
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import redis as redis_lib
import typer
from typer.testing import CliRunner

from aegis.__main__ import app
from aegis.commands import deploy_agent as agent
from aegis.commands.deploy_backup import BACKUP_TIMESTAMP_RE
from aegis.core.component_files import PROJECT_SLUG_PLACEHOLDER, get_template_path
from aegis.core.provision import digitalocean
from tests.cli.test_utils import strip_ansi_codes

DO_TOKEN = "do-secret-token-5678"
SENT_TOKEN = "dop_v1_sent-by-the-app-wxyz"  # one the Overseer sends
PK, SK = "pk1_" + "c" * 24 + "pkey", "sk1_" + "d" * 24 + "skey"  # Porkbun's
SYSTEM = get_template_path() / PROJECT_SLUG_PLACEHOLDER / "app" / "services" / "system"
FAKE_AEGIS = """\
import os, sys
print("ran " + " ".join(sys.argv[1:]))
print("token " + os.environ.get("DIGITALOCEAN_TOKEN", ""))
print("dns " + os.environ.get("PORKBUN_API_KEY", ""))
if os.environ.get("FAKE_WAIT_FOR"):  # until a look is answered, or 5s
    import time
    for _ in range(50):
        if os.path.exists(os.environ["FAKE_WAIT_FOR"]):
            print("answered alongside")
            break
        time.sleep(0.1)
if os.environ.get(PROGRESS_ENV):
    print(PROGRESS_LINE)
    print("bar of " + os.environ[PROGRESS_ENV])
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""
PROGRESS = {"steps": ["server", "boot"], "at": "boot"}
FAKE_AEGIS = (
    f"PROGRESS_ENV = {agent.PROTOCOL['progress_env']!r}\n"
    f"PROGRESS_LINE = {agent._protocol.progress_line(**PROGRESS)!r}\n"
) + FAKE_AEGIS


class FakeRedis:
    """The sync calls the agent makes, over dicts. ``on_empty`` runs when a
    BLPOP finds nothing, so a test can stop the loop once it is drained."""

    def __init__(self, on_empty: Any = None) -> None:
        self.lists: dict[str, list[str]] = {}
        self.strings: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.ttl: dict[str, int] = {}
        self.on_empty = on_empty

    def rpush(self, key: str, *values: str) -> None:
        self.lists.setdefault(key, []).extend(values)

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[str, str] | None:
        for key in keys:
            if self.lists.get(key):
                return key, self.lists[key].pop(0)
        if self.on_empty:
            self.on_empty()
        return None

    def ping(self) -> bool:
        return True

    def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and key in self.strings:
            return None
        self.strings[key] = value
        if ex:
            self.ttl[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.strings.get(key)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        return list(self.lists.get(key, []))

    def scan_iter(self, match: str) -> list[str]:
        prefix = match.removesuffix("*")
        return [k for k in self.hashes if k.startswith(prefix)]

    def exists(self, key: str) -> int:
        return int(key in self.strings)

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.strings.pop(key, None)

    def hset(self, key: str, mapping: dict[str, Any]) -> None:
        self.hashes.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds


class _Async:
    """``FakeRedis`` as the app's ``redis.asyncio`` client."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis

    def __getattr__(self, name: str) -> Any:
        call = getattr(self._redis, name)

        async def awaited(*args: Any, **kwargs: Any) -> Any:
            return call(*args, **kwargs)

        return awaited


def _load(name: str, path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def app_store(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The app's own ``RedisJobStore`` class, out of the template, so the
    record the agent writes is read the way the jobs API reads it."""
    for name in ("app", "app.core", "app.services", "app.services.system"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    log = types.ModuleType("app.core.log")
    log.logger = logging.getLogger("app")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.log", log)
    _load("app.services.system.jobs", SYSTEM / "jobs.py", monkeypatch)
    return _load(
        "app.services.system.job_store", SYSTEM / "job_store.py", monkeypatch
    ).RedisJobStore


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "fake_aegis.py"
    script.write_text(FAKE_AEGIS)
    monkeypatch.setattr(agent, "AEGIS", [sys.executable, str(script)])
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", DO_TOKEN)
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    root = tmp_path / "my-app"
    root.mkdir()
    return root


def _request(
    redis: FakeRedis,
    store_class: Any,
    action: str,
    args: dict[str, str] | None = None,
    at: datetime | None = None,
    token: Any = None,
    dns_keys: Any = None,
) -> str:
    """What the app's ``enqueue`` does: the job record, then the request."""
    job_id = uuid.uuid4().hex
    store = store_class(_Async(redis))
    asyncio.run(
        store.create(job_id, f"deploy:{action}", "Waiting for the deploy agent")
    )
    when = (at or datetime.now(UTC)).isoformat()
    request = {"job_id": job_id, "action": action, "args": args or {}, "by": "ada"}
    if token is not None:
        request["token"] = token
    if dns_keys is not None:
        request["dns_keys"] = dns_keys
    redis.rpush(agent.PROTOCOL["requests"], json.dumps(request | {"at": when}))
    if not agent._protocol.is_kept(action):  # the newest job the page shows
        redis.strings[agent.PROTOCOL["last"]] = job_id
    return job_id


def _serve(redis: FakeRedis, root: Path) -> None:
    """Run the agent until the queue is empty."""
    stop = threading.Event()
    redis.on_empty = stop.set
    agent.serve(redis, root, stop=stop)


def _job(redis: FakeRedis, store_class: Any, job_id: str) -> Any:
    return asyncio.run(store_class(_Async(redis)).get(job_id))


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


def test_a_valid_request_passes_with_its_empty_optionals_dropped() -> None:
    args = {
        "provider": "digitalocean",
        "size": "s-1vcpu-2gb",
        "region": "nyc3",
        "price": "12.00",
    }
    assert agent.validate("provision", args | {"domain": ""}) == args


@pytest.mark.parametrize(
    ("action", "args"),
    [
        ("shell", {}),  # not an action
        ("deploy", {"rolling": "1"}),  # not one of its arguments
        ("destroy", {}),  # its confirmation missing
        ("rollback", {"backup": "latest; rm -rf /"}),
        ("rollback", {"backup": "--help"}),
        (
            "provision",
            {
                "provider": "digitalocean",
                "size": "--yes",
                "region": "nyc3",
                "price": "12.00",
            },
        ),
        ("catalog", {"provider": "linode"}),
        ("destroy", {"confirm": ["my-app"]}),
    ],
)
def test_anything_else_is_refused(action: str, args: dict[str, Any]) -> None:
    with pytest.raises(agent.RefusedError):
        agent.validate(action, args)


def test_a_rollback_takes_the_backups_own_timestamps() -> None:
    assert agent.PROTOCOL["args"]["backup"] == BACKUP_TIMESTAMP_RE.pattern.strip("^$")


# ---------------------------------------------------------------------------
# Where Redis is
# ---------------------------------------------------------------------------


def test_redis_is_found_where_docker_published_this_checkouts(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asked of Docker each time, by the checkout compose ran in, never a
    port written down (``.env.ports``, which may since be another
    project's) nor the project's name (another checkout's, too)."""
    for key in ("REDIS_URL_LOCAL", "REDIS_URL"):
        monkeypatch.delenv(key, raising=False)
    asked: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        asked.append(args)
        return "c0ffee\n" if args[0] == "ps" else "127.0.0.1:6380\n[::1]:6380\n"

    (project / ".env").write_text("REDIS_URL=redis://redis:6379/2\n")
    (project / ".env.ports").write_text("REDIS_HOST_PORT=6381\n")
    assert agent.redis_url(project, docker) == "redis://127.0.0.1:6380/2"
    ps, port = asked
    assert f"label=com.docker.compose.project.working_dir={project}" in ps
    assert "label=com.docker.compose.service=redis" in ps
    assert port == ("port", "c0ffee", "6379")
    monkeypatch.setenv("REDIS_URL_LOCAL", "redis://10.0.0.5:7000")
    assert agent.redis_url(project, docker) == "redis://10.0.0.5:7000"


def test_a_checkout_whose_redis_is_not_running_has_none(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("REDIS_URL_LOCAL", raising=False)
    with pytest.raises(agent.DockerError):
        agent.redis_url(project, lambda *args: "")


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def test_the_heartbeat_names_the_providers_it_has_tokens_for(project: Path) -> None:
    redis = FakeRedis()
    seen: list[str | None] = []
    stop = threading.Event()

    def drained() -> None:
        seen.append(redis.get(agent.PROTOCOL["heartbeat"]))
        stop.set()

    redis.on_empty = drained
    agent.serve(redis, project, stop=stop)
    beat = json.loads(seen[0] or "{}")
    assert beat["providers"] == ["digitalocean"]
    assert beat["revision"] == agent.PROTOCOL["revision"]
    assert beat["actions"] == list(agent.PROTOCOL["actions"])
    assert beat["pid"] and beat["host"] and beat["version"]
    assert beat["root"] == str(project)  # which checkout deploys
    assert DO_TOKEN not in (seen[0] or "")
    assert redis.ttl[agent.PROTOCOL["heartbeat"]] > 0
    # Stopping takes it down: the Overseer stops offering the actions.
    assert redis.get(agent.PROTOCOL["heartbeat"]) is None


def test_a_request_runs_and_its_output_streams_into_the_job(
    project: Path, app_store: Any
) -> None:
    redis = FakeRedis()
    job_id = _request(redis, app_store, "rollback", {"backup": "2026-10-01_020000"})
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.status == "done"
    ran = f"ran deploy-rollback --project-path {project} --backup 2026-10-01_020000"
    assert job.result["lines"][0] == ran
    assert job.label == job.result["lines"][-1]
    # The token reached the command, and only its last four the job.
    assert job.result["lines"][1] == "token ...5678"
    assert DO_TOKEN not in json.dumps(redis.hashes)


def test_the_commands_step_is_kept_beside_its_output_not_in_it(
    project: Path, app_store: Any
) -> None:
    """A step bar's place, which the command prints only for the agent."""
    redis = FakeRedis()
    job_id = _request(redis, app_store, "rollback", {"backup": "2026-10-01_020000"})
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.result["progress"] == PROGRESS
    marker = agent.PROTOCOL["progress"]
    assert not any(marker in line for line in [*job.result["lines"], job.label])
    # The command is told which action's bar it marks: nested ones stay out.
    assert "bar of rollback" in job.result["lines"]


def test_a_look_is_answered_while_a_command_runs(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A catalog or account asked while a server is being made is answered
    beside it, not queued behind it until it is too old to run."""
    flag = project / "answered"
    monkeypatch.setenv("FAKE_WAIT_FOR", str(flag))
    monkeypatch.setattr(agent, "_found", lambda *args: flag.touch() or {"sizes": []})
    redis = FakeRedis()
    running = _request(redis, app_store, "rollback", {"backup": "2026-10-01_020000"})
    look = _request(redis, app_store, "catalog", {"provider": "digitalocean"})
    _serve(redis, project)
    assert "answered alongside" in _job(redis, app_store, running).result["lines"]
    assert _job(redis, app_store, look).status == "done"


def test_the_job_record_is_the_apps(app_store: Any) -> None:
    store = sys.modules[app_store.__module__]
    assert (agent.JOB_PREFIX, agent.JOB_KEEP_SECONDS) == (
        store.KEY_PREFIX,
        store.KEEP_SECONDS,
    )


def test_a_command_that_fails_fails_the_job(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_EXIT", "3")
    redis = FakeRedis()
    job_id = _request(redis, app_store, "deploy")
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.status == "failed"
    assert "aegis deploy" in job.error and "3" in job.error
    assert job.result["lines"][0] == f"ran deploy --project-path {project}"


def test_a_destroy_carries_the_typed_name(project: Path, app_store: Any) -> None:
    redis = FakeRedis()
    job_id = _request(redis, app_store, "destroy", {"confirm": "my-app"})
    _serve(redis, project)
    line = _job(redis, app_store, job_id).result["lines"][0]
    assert line == f"ran deploy-destroy --project-path {project} --confirm my-app"


def test_a_stale_request_is_failed_not_run(project: Path, app_store: Any) -> None:
    redis = FakeRedis()
    old = datetime.now(UTC) - timedelta(minutes=30)
    job_id = _request(redis, app_store, "deploy", at=old)
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.status == "failed" and "30" in job.error
    assert not job.result["lines"]


def test_a_refused_request_says_why(project: Path, app_store: Any) -> None:
    redis = FakeRedis()
    job_id = _request(redis, app_store, "rollback", {"backup": "$(reboot)"})
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.status == "failed" and "backup" in job.error


def test_an_unexpected_error_fails_its_job_and_the_agent_listens_on(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One request going wrong (here, a docker line it cannot read) fails
    that job saying what happened, with any token masked, and the next
    request still runs: the agent never dies under make serve unseen."""
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", DO_TOKEN)

    def broken(root: Path) -> dict[str, Any]:
        raise ValueError(f"Not a size: -- ({DO_TOKEN})")

    monkeypatch.setattr(agent, "measure", broken)
    redis = FakeRedis()
    first = _request(redis, app_store, "footprint", {})
    then = _request(redis, app_store, "deploy")
    _serve(redis, project)
    job = _job(redis, app_store, first)
    assert job.status == "failed" and "Not a size: --" in job.error
    _nowhere(redis, DO_TOKEN)
    assert _job(redis, app_store, then).status == "done"


def test_redis_dropping_mid_job_leaves_the_agent_listening(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stack restarting while a job writes its record: the lost writes
    are that record's alone (the next puts it right), the command runs on
    to the end, and the next request runs."""
    redis = FakeRedis()
    first = _request(redis, app_store, "deploy")
    then = _request(redis, app_store, "deploy")
    writes = redis.hset
    down = {"left": 2}  # the job's first line, then its failure

    def flaky(key: str, mapping: dict[str, Any]) -> None:
        if first in key and down["left"]:
            down["left"] -= 1
            raise redis_lib.ConnectionError("Connection refused")
        writes(key, mapping)

    monkeypatch.setattr(redis, "hset", flaky)
    _serve(redis, project)
    assert _job(redis, app_store, first).status == "done"
    assert _job(redis, app_store, then).status == "done"


def _nowhere(redis: FakeRedis, token: str) -> None:
    """The token is in no job, list or key the agent left behind."""
    assert token not in json.dumps([redis.hashes, redis.lists, redis.strings])


SIZE = {
    "slug": "s-1vcpu-2gb",
    "description": "Basic",
    "memory": 2048,
    "vcpus": 1,
    "disk": 50,
    "regions": ["nyc3"],
    "available": True,
}


def _price_api(monkeypatch: pytest.MonkeyPatch, price: float) -> list[str]:
    """DigitalOcean's size and region lists, the size at ``price``."""
    tokens: list[str] = []
    answer = {
        "sizes": [SIZE | {"price_monthly": price}],
        "regions": [{"slug": "nyc3", "name": "New York 3", "available": True}],
    }

    def requester(base: str, token: str) -> Any:
        assert base == digitalocean.API_URL
        tokens.append(token)
        return lambda method, path, body=None: answer

    monkeypatch.setattr(agent, "json_requester", requester)
    return tokens


QUOTED = {"provider": "digitalocean", "size": "s-1vcpu-2gb", "region": "nyc3"}
CATALOGUED = {"provider": "digitalocean"}
CATALOG_KEY = "deploy:catalog:digitalocean"


def test_a_catalog_is_kept_in_redis_for_the_overseer(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider's sizes and regions, as its client lists them, with
    its currency, for an hour; the token is in none of it."""
    tokens = _price_api(monkeypatch, 12)
    redis = FakeRedis()
    job_id = _request(redis, app_store, "catalog", CATALOGUED)
    _serve(redis, project)
    assert _job(redis, app_store, job_id).status == "done"
    found = json.loads(redis.strings[CATALOG_KEY])
    assert found["currency"] == "USD"
    assert found["regions"] == [{"slug": "nyc3", "name": "New York 3"}]
    assert [(s["slug"], s["prices"]) for s in found["sizes"]] == [
        ("s-1vcpu-2gb", {"nyc3": "12.00"})
    ]
    assert redis.ttl[CATALOG_KEY] == agent.PROTOCOL["actions"]["catalog"]["seconds"]
    assert tokens == [DO_TOKEN]
    _nowhere(redis, DO_TOKEN)


def test_the_stacks_footprint_is_kept_in_redis_for_the_overseer(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured here (``aegis.core.footprint``), for a while, in the
    background; it needs no token."""
    measured = {"services": [], "volumes": [], "images": 0}
    monkeypatch.setattr(agent, "measure", lambda root: measured)
    redis = FakeRedis()
    job_id = _request(redis, app_store, "footprint", {})
    _serve(redis, project)
    assert _job(redis, app_store, job_id).status == "done"
    key = "deploy:footprint"
    assert json.loads(redis.strings[key]) == measured
    assert redis.ttl[key] == agent.PROTOCOL["actions"]["footprint"]["seconds"]


def test_what_is_already_kept_is_not_fetched_again(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two pages asking at once queue two requests; the second finds the
    first's answer and is done without asking the provider."""
    tokens = _price_api(monkeypatch, 12)
    redis = FakeRedis()
    first = _request(redis, app_store, "catalog", CATALOGUED)
    second = _request(redis, app_store, "catalog", CATALOGUED)
    _serve(redis, project)
    assert [_job(redis, app_store, j).status for j in (first, second)] == [
        "done",
        "done",
    ]
    assert tokens == [DO_TOKEN]  # asked once


def test_docker_failing_fails_the_footprint_saying_why(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(root: Path) -> dict[str, Any]:
        raise agent.DockerError("Cannot connect to the Docker daemon")

    monkeypatch.setattr(agent, "measure", broken)
    redis = FakeRedis()
    job_id = _request(redis, app_store, "footprint", {})
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.status == "failed" and "Docker daemon" in job.error


def test_the_account_is_kept_with_its_currency(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the account runs now, as its client lists it, for a while."""
    tokens: list[str] = []

    def requester(base: str, token: str) -> Any:
        tokens.append(token)
        answers = {
            "/droplets?per_page=200": {"droplets": []},
            "/customers/my/balance": {"month_to_date_usage": "3.10"},
        }
        return lambda method, path, body=None: answers[path]

    monkeypatch.setattr(agent, "json_requester", requester)
    redis = FakeRedis()
    job_id = _request(redis, app_store, "account", CATALOGUED)
    _serve(redis, project)
    assert _job(redis, app_store, job_id).status == "done"
    key = "deploy:account:digitalocean"
    found = json.loads(redis.strings[key])
    assert found == {
        "servers": [],
        "month_to_date": "3.10",
        "missing": [],
        "currency": "USD",
    }
    assert redis.ttl[key] == agent.PROTOCOL["actions"]["account"]["seconds"]
    assert tokens == [DO_TOKEN]


def test_a_provision_forgets_the_kept_account(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It changed what the account runs: the next look asks again."""
    _price_api(monkeypatch, 12)
    redis = FakeRedis()
    redis.strings["deploy:account:digitalocean"] = json.dumps({"servers": []})
    _request(redis, app_store, "provision", QUOTED | {"price": "12.00"})
    _serve(redis, project)
    assert "deploy:account:digitalocean" not in redis.strings


LISTED = [{"name": "2026-10-15_014324", "size": "172M", "database": True}]


def test_the_servers_backups_are_kept_for_the_overseer(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Listed on the server in the background (``list_backups``): a
    rollback is asked for one of them, never a typed name."""
    _server(project)
    seen: list[str] = []
    monkeypatch.setattr(
        agent, "list_backups", lambda run, path: seen.append(path) or LISTED
    )
    redis = FakeRedis()
    job_id = _request(redis, app_store, "backups", {})
    _serve(redis, project)
    assert _job(redis, app_store, job_id).status == "done"
    assert json.loads(redis.strings["deploy:backups"]) == {"backups": LISTED}
    assert seen == ["/opt/app"]


def _server(project: Path) -> None:
    (project / ".aegis").mkdir(exist_ok=True)
    (project / ".aegis" / "deploy.yml").write_text(
        "server:\n  host: h\n  user: u\n  path: /opt/app\n"
    )


def test_the_servers_deploy_history_is_kept_for_the_overseer(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The protocol's ``history``: its last line is the JSON, whatever the
    app logged before it."""
    _server(project)
    (project / "app" / "cli").mkdir(parents=True)
    (project / "app" / "cli" / "deploy_cli.py").write_text("")
    rows = [{"build_id": "1c956eef", "health": "passed"}]
    ran: list[str] = []

    def remote(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        ran.append(command)
        out = "a log line\n" + json.dumps(rows) + "\n"
        return subprocess.CompletedProcess([], 0, out, "")

    monkeypatch.setattr(agent, "_run_remote_capture", remote)
    redis = FakeRedis()
    job_id = _request(redis, app_store, "history", {})
    _serve(redis, project)
    assert _job(redis, app_store, job_id).status == "done"
    assert json.loads(redis.strings["deploy:history"]) == {"deploys": rows}
    (command,) = ran
    assert "exec -T webserver python -m app.cli.main deploy history" in command


def test_the_servers_missing_files_are_kept_for_the_overseer(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The protocol's ``storage``: the server's ``storage check``, whose
    stdout is the keys alone (aegis-stack#1681)."""
    _server(project)
    gone = "sha256/aa/aa/" + "a" * 64
    ran: list[str] = []

    def remote(host: str, user: str, command: str) -> subprocess.CompletedProcess:
        ran.append(command)
        return subprocess.CompletedProcess([], 1, gone + "\n", "1 missing")

    monkeypatch.setattr(agent, "_run_remote_capture", remote)
    redis = FakeRedis()
    job_id = _request(redis, app_store, "storage", {})
    _serve(redis, project)
    assert _job(redis, app_store, job_id).status == "done"
    assert json.loads(redis.strings["deploy:storage"]) == {"missing": [gone]}
    (command,) = ran
    assert "exec -T webserver python -m app.cli.main storage check" in command


def test_a_command_forgets_what_it_may_have_changed(
    project: Path, app_store: Any
) -> None:
    """The backups, the history and the missing files
    (``until_a_command``); not a catalog."""
    redis = FakeRedis()
    changed = {"deploy:backups", "deploy:history", "deploy:storage"}
    for key in (*changed, CATALOG_KEY):
        redis.strings[key] = json.dumps({})
    _request(redis, app_store, "deploy")
    _serve(redis, project)
    assert set(redis.strings) & changed == set()
    assert CATALOG_KEY in redis.strings


def test_a_job_left_running_by_a_stopped_agent_fails_saying_so(
    project: Path, app_store: Any
) -> None:
    """Only one agent serves a project: a newest job still running when it
    starts was the last one's, cut off, and would hold the page's buttons
    forever. One still on the queue is not: it is about to run."""
    redis = FakeRedis()
    orphans = [_request(redis, app_store, a) for a in ("deploy", "backups")]
    redis.lists.clear()  # taken by the agent that stopped
    _serve(redis, project)
    # A look too: the rollback's list would wait on it until it expired.
    for orphan in orphans:
        job = _job(redis, app_store, orphan)
        assert job.status == "failed" and "stopped" in job.error

    redis = FakeRedis()
    queued = _request(redis, app_store, "deploy")
    _serve(redis, project)
    assert _job(redis, app_store, queued).status == "done"


def test_a_catalog_without_the_token_says_which(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DIGITALOCEAN_TOKEN")
    redis = FakeRedis()
    job_id = _request(redis, app_store, "catalog", CATALOGUED)
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.status == "failed" and "DIGITALOCEAN_TOKEN" in job.error


def test_provisioning_rechecks_the_price_first(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _price_api(monkeypatch, 14)
    redis = FakeRedis()
    job_id = _request(redis, app_store, "provision", QUOTED | {"price": "12.00"})
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.status == "failed" and "14.00" in job.error
    assert not job.result["lines"]  # nothing ran


def test_provisioning_at_the_confirmed_price_runs(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _price_api(monkeypatch, 12)
    redis = FakeRedis()
    args = QUOTED | {"price": "12.00", "domain": "app.example.com"}
    job_id = _request(redis, app_store, "provision", args)
    _serve(redis, project)
    line = _job(redis, app_store, job_id).result["lines"][0]
    assert line == (
        f"ran deploy-provision --project-path {project} --yes --provider "
        "digitalocean --size s-1vcpu-2gb --region nyc3 --domain app.example.com"
    )


def test_a_token_the_app_sends_is_used_over_the_environments(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = _price_api(monkeypatch, 12)
    redis = FakeRedis()
    job_id = _request(redis, app_store, "catalog", CATALOGUED, token=SENT_TOKEN)
    _serve(redis, project)
    assert _job(redis, app_store, job_id).status == "done"
    assert tokens == [SENT_TOKEN]
    _nowhere(redis, SENT_TOKEN)


def test_a_sent_token_reaches_the_command_in_its_environment_never_its_args(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _price_api(monkeypatch, 12)
    redis = FakeRedis()
    args = QUOTED | {"price": "12.00"}
    job_id = _request(redis, app_store, "provision", args, token=SENT_TOKEN)
    _serve(redis, project)
    ran, token = _job(redis, app_store, job_id).result["lines"][:2]
    assert ran.startswith("ran deploy-provision") and SENT_TOKEN not in ran
    assert token == "token ...wxyz"  # masked in the line the job keeps
    _nowhere(redis, SENT_TOKEN)


def test_a_provisions_dns_keys_reach_its_command_masked_never_its_args(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _price_api(monkeypatch, 12)
    redis = FakeRedis()
    args = QUOTED | {
        "price": "12.00",
        "domain": "app.example.com",
        "dns": "porkbun",
        "allowlist": "203.0.113.9/32",
    }
    keys = {"PORKBUN_API_KEY": PK, "PORKBUN_SECRET_KEY": SK}
    job_id = _request(
        redis, app_store, "provision", args, token=SENT_TOKEN, dns_keys=keys
    )
    _serve(redis, project)
    ran, _, dns = _job(redis, app_store, job_id).result["lines"][:3]
    assert "--dns porkbun" in ran and PK not in ran
    assert "--allowlist 203.0.113.9/32" in ran
    assert dns == "dns ...pkey"
    _nowhere(redis, PK)
    _nowhere(redis, SK)


@pytest.mark.parametrize(
    "keys",
    [
        {"PATH": "/tmp/evil:/usr/bin"},  # a name no DNS provider reads
        {"PORKBUN_API_KEY": "not a key; rm -rf"},
        "PORKBUN_API_KEY=pk1_x",
    ],
)
def test_dns_keys_other_than_a_dns_providers_are_refused(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch, keys: Any
) -> None:
    """Only a DNS provider's own variables reach the command: anything else
    (``PATH``, ``LD_PRELOAD``) would change what it runs."""
    _price_api(monkeypatch, 12)
    redis = FakeRedis()
    args = QUOTED | {"price": "12.00", "domain": "app.example.com", "dns": "porkbun"}
    job_id = _request(
        redis, app_store, "provision", args, token=SENT_TOKEN, dns_keys=keys
    )
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.status == "failed" and "DNS" in job.error
    assert not job.result["lines"]


def test_a_destroy_sends_the_token_of_the_provisioned_servers_provider(
    project: Path, app_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DIGITALOCEAN_TOKEN")
    (project / ".aegis").mkdir()
    (project / ".aegis" / "deploy.yml").write_text(
        "provision:\n  provider: digitalocean\n"
    )
    redis = FakeRedis()
    args = {"confirm": "my-app"}
    job_id = _request(redis, app_store, "destroy", args, token=SENT_TOKEN)
    _serve(redis, project)
    assert _job(redis, app_store, job_id).result["lines"][1] == "token ...wxyz"
    _nowhere(redis, SENT_TOKEN)


@pytest.mark.parametrize(
    ("action", "args", "token"),
    [
        ("catalog", CATALOGUED, "has a space in it"),
        ("catalog", CATALOGUED, "short"),
        ("catalog", CATALOGUED, "x" * 600),
        ("catalog", CATALOGUED, "line\nbreak-token"),
        ("catalog", CATALOGUED, ["dop_v1_in-a-list"]),
        ("deploy", {}, SENT_TOKEN),  # an action that takes no token
    ],
)
def test_a_malformed_or_unwanted_token_is_refused_and_nothing_runs(
    project: Path,
    app_store: Any,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    args: dict[str, str],
    token: Any,
) -> None:
    tokens = _price_api(monkeypatch, 12)
    redis = FakeRedis()
    job_id = _request(redis, app_store, action, args, token=token)
    _serve(redis, project)
    job = _job(redis, app_store, job_id)
    assert job.status == "failed" and "token" in job.error
    assert not job.result["lines"] and not tokens
    assert str(token) not in job.error


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


def test_every_action_runs_a_command_that_takes_its_arguments() -> None:
    """The protocol and the commands cannot drift: each argument the agent
    passes is one of its command's options (the price it checks itself)."""
    commands = typer.main.get_command(app).commands  # type: ignore[attr-defined]
    for action, spec in agent.PROTOCOL["actions"].items():
        if "command" not in spec:  # answered by the agent itself
            continue
        name, *flags = spec["command"]
        options = {o for param in commands[name].params for o in param.opts}
        args = (*spec.get("required", ()), *spec.get("optional", ()))
        wanted = {"--project-path", *flags, *(f"--{a}" for a in args if a != "price")}
        assert wanted <= options, f"{action}: {wanted - options}"


def test_help() -> None:
    result = CliRunner().invoke(app, ["deploy-agent", "--help"])
    assert result.exit_code == 0
    assert "--project-path" in strip_ansi_codes(result.output)


def _beat_of(redis: FakeRedis, pid: int) -> None:
    """Another agent's heartbeat on this project's Redis."""
    beat = {"host": agent.socket.gethostname(), "pid": pid, "root": "/elsewhere"}
    redis.strings[agent.PROTOCOL["heartbeat"]] = json.dumps(beat)


def _found(redis: FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    """The project's Redis is ``redis``, up."""
    monkeypatch.setattr(agent, "redis_url", lambda root: "redis://127.0.0.1:1")
    monkeypatch.setattr(agent.redis.Redis, "from_url", lambda *a, **k: redis)


def test_a_second_agent_for_the_project_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two would take turns at the requests (two deploys at once), and each
    would fail the jobs the other is running."""
    redis = FakeRedis()
    _beat_of(redis, os.getppid())  # alive
    _found(redis, monkeypatch)
    with pytest.raises(agent.RefusedError, match="/elsewhere"):
        agent.connect(project, threading.Event())
    assert "Listening" not in capsys.readouterr().out
    assert "/elsewhere" in redis.strings[agent.PROTOCOL["heartbeat"]]  # not taken down


def test_a_dead_agents_heartbeat_does_not_hold_the_project(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Killed without taking it down (make serve stopping it): its heartbeat
    lingers a few seconds, and the next agent listens anyway."""
    redis = FakeRedis()
    gone = subprocess.Popen([sys.executable, "-c", ""])
    gone.wait()
    _beat_of(redis, gone.pid)
    _found(redis, monkeypatch)
    assert agent.connect(project, threading.Event()) is redis
    beat = json.loads(redis.strings[agent.PROTOCOL["heartbeat"]])
    assert beat["pid"] == os.getpid()  # taken over


def test_the_agent_stops_once_whoever_started_it_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """make serve killed outright: left behind, the agent would listen for
    a stack nobody runs, and stand beside the next make serve's."""
    monkeypatch.setattr(agent, "POLL_SECONDS", 0.01)
    parent = {"pid": os.getppid()}
    monkeypatch.setattr(agent.os, "getppid", lambda: parent["pid"])
    stop = threading.Event()
    agent.watch_parent(stop)
    assert not stop.wait(0.05)
    parent["pid"] = 1  # reparented
    assert stop.wait(2)


class _Flaky(FakeRedis):
    """A Redis not up the first time it is asked."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def ping(self) -> bool:
        self.calls += 1
        if self.calls == 1:
            raise agent.redis.ConnectionError("Connection refused")
        return True


def test_it_waits_for_its_projects_redis_saying_why_once(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Started beside the stack (make serve), the agent is usually up
    before Redis is: asked where it is again each try, as the stack may
    come up on another port."""
    monkeypatch.setattr(agent, "REDIS_RETRY_SECONDS", 0)
    places = iter([agent.DockerError("not running"), "redis://127.0.0.1:1"])

    def where(root: Path) -> str:
        place = next(places, "redis://127.0.0.1:2")
        if isinstance(place, Exception):
            raise place
        return place

    client = _Flaky()
    monkeypatch.setattr(agent, "redis_url", where)
    monkeypatch.setattr(agent.redis.Redis, "from_url", lambda *a, **k: client)
    assert agent.connect(project, threading.Event()) is client
    assert client.calls == 2
    said = strip_ansi_codes(capsys.readouterr().out)
    assert said.count("not running") == 1
    assert "redis://127.0.0.1:2" in said  # listening, where


def test_it_listens_again_wherever_its_redis_comes_back(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stack restarting takes Redis down; the agent finds it again (on
    whatever port it came back on) rather than dying with it."""
    stop = threading.Event()
    first, starting, then = FakeRedis(), FakeRedis(), FakeRedis(on_empty=stop.set)

    def gone(*args: Any, **kwargs: Any) -> Any:
        raise agent.redis.ConnectionError("gone")

    first.blpop = gone  # type: ignore[method-assign]  # between requests
    starting.scan_iter = gone  # type: ignore[method-assign]  # while starting
    clients = iter([first, starting, then])
    monkeypatch.setattr(agent, "connect", lambda root, stop: next(clients, None))
    agent.listen(project, stop)
    assert stop.is_set() and next(clients, None) is None
