"""Tests for ``aegis deploy-provision`` / ``aegis deploy-destroy`` and their clients.

No test touches a real cloud or DNS API: every provider and Cloudflare call
goes through a ``Requester`` callable, faked here by ``FakeAPI``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from aegis.__main__ import app
from aegis.commands import deploy_provision as cmd
from aegis.core.provision import digitalocean, hetzner, wait
from aegis.core.provision.cloudflare import CloudflareDNS
from aegis.core.provision.hetzner import HetznerClient
from aegis.core.provision.http import (
    ProvisionError,
    json_requester,
    mask_token,
)
from aegis.core.provision.provider import (
    cloud_init_user_data,
    monthly_price,
    ssh_fingerprint,
)
from tests.cli.test_utils import strip_ansi_codes

RUNNER = CliRunner()
HCLOUD = "hcloud-secret-token-1234"
DO_TOKEN = "do-secret-token-5678"
CF = "cf-secret-token-9876"
PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl me@laptop"
IP = "203.0.113.7"


class FakeAPI:
    """Route table standing in for an HTTP API: (method, path) -> response."""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, path, body))
        response = self.routes[(method, path)]
        if isinstance(response, Exception):
            raise response
        return response

    def called(self, method: str, path: str) -> bool:
        return any(c[0] == method and c[1] == path for c in self.calls)


def _hetzner_routes() -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/server_types?per_page=50"): {
            "server_types": [
                {
                    "name": "cx23",
                    "cores": 2,
                    "memory": 4.0,
                    "disk": 40,
                    "cpu_type": "shared",
                    "architecture": "x86",
                    "deprecation": None,
                    "prices": [
                        {
                            "location": "nbg1",
                            "price_monthly": {"net": "3.4900", "gross": "4.1531"},
                        }
                    ],
                }
            ]
        },
        ("GET", "/locations?per_page=50"): {
            "locations": [{"name": "nbg1", "city": "Nuremberg", "country": "DE"}]
        },
        ("GET", f"/ssh_keys?fingerprint={_fingerprint()}"): {"ssh_keys": []},
        ("POST", "/ssh_keys"): {"ssh_key": {"id": 11}},
        ("POST", "/servers"): {
            "server": {
                "id": 42,
                "status": "initializing",
                "public_net": {"ipv4": {"ip": IP}},
            }
        },
        ("GET", "/servers/42"): {
            "server": {
                "id": 42,
                "status": "running",
                "public_net": {"ipv4": {"ip": IP}},
            }
        },
        ("DELETE", "/servers/42"): {"action": {"id": 1}},
        ("DELETE", "/ssh_keys/11"): {},
    }


def _do_routes() -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/sizes?per_page=200"): {
            "sizes": [
                {
                    "slug": "s-1vcpu-2gb",
                    "description": "Basic",
                    "memory": 2048,
                    "vcpus": 1,
                    "disk": 50,
                    "price_monthly": 12.0,
                    "regions": ["tor1", "fra1"],
                    "available": True,
                }
            ]
        },
        ("GET", "/regions?per_page=200"): {
            "regions": [
                {"slug": "tor1", "name": "Toronto 1", "available": True},
                {"slug": "fra1", "name": "Frankfurt 1", "available": True},
                {"slug": "sgp1", "name": "Singapore 1", "available": True},
            ]
        },
        ("GET", f"/account/keys/{_fingerprint()}"): ProvisionError(
            "not found", status=404
        ),
        ("POST", "/account/keys"): {"ssh_key": {"id": 21}},
        # The IP arrives after create, once the droplet is up.
        ("POST", "/droplets"): {
            "droplet": {"id": 77, "status": "new", "networks": {"v4": []}}
        },
        ("GET", "/droplets/77"): {
            "droplet": {
                "id": 77,
                "status": "active",
                "networks": {
                    "v4": [
                        {"ip_address": "10.10.0.5", "type": "private"},
                        {"ip_address": IP, "type": "public"},
                    ]
                },
            }
        },
        ("POST", "/firewalls"): {"firewall": {"id": "fw-1"}},
        ("DELETE", "/firewalls/fw-1"): {},
        ("DELETE", "/droplets/77"): {},
        ("DELETE", "/account/keys/21"): {},
    }


def _cloudflare_routes() -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/zones?name=app.example.com"): {"result": []},
        ("GET", "/zones?name=example.com"): {"result": [{"id": "zone1"}]},
        ("POST", "/zones/zone1/dns_records"): {"result": {"id": "rec1"}},
        ("DELETE", "/zones/zone1/dns_records/rec1"): {"result": {"id": "rec1"}},
    }


def _fingerprint() -> str:
    return ssh_fingerprint(PUBKEY)


# ---------------------------------------------------------------------------
# Clients and helpers
# ---------------------------------------------------------------------------


def test_mask_token_shows_last_four_only() -> None:
    assert mask_token(HCLOUD) == "...1234"
    assert HCLOUD[:-4] not in mask_token(HCLOUD)


def test_ssh_fingerprint_is_md5_colon_form() -> None:
    fp = _fingerprint()
    assert len(fp.split(":")) == 16


def test_monthly_price_reads_gross_for_location() -> None:
    client = HetznerClient(FakeAPI(_hetzner_routes()))
    assert monthly_price(client, "cx23", "nbg1") == "4.15"


def test_the_catalog_lists_what_can_be_created_where() -> None:
    """Server types still sold, priced (gross) per location, grouped as
    Hetzner sells them; locations by city."""
    api = FakeAPI(
        {
            ("GET", "/server_types?per_page=50"): {
                "server_types": [
                    {
                        "name": "cax11",
                        "cores": 2,
                        "memory": 4.0,
                        "disk": 40,
                        "cpu_type": "shared",
                        "architecture": "arm",
                        "deprecation": None,
                        "prices": [
                            {"location": "fsn1", "price_monthly": {"gross": "4.5100"}}
                        ],
                    },
                    {
                        "name": "cx11",
                        "cores": 1,
                        "memory": 2.0,
                        "disk": 20,
                        "cpu_type": "shared",
                        "architecture": "x86",
                        "deprecation": {"announced": "2024-06-06T00:00:00+00:00"},
                        "prices": [
                            {"location": "fsn1", "price_monthly": {"gross": "4.1500"}}
                        ],
                    },
                ]
            },
            ("GET", "/locations?per_page=50"): {
                "locations": [{"name": "fsn1", "city": "Falkenstein", "country": "DE"}]
            },
        }
    )
    assert HetznerClient(api).catalog() == {
        "sizes": [
            {
                "slug": "cax11",
                "group": "Shared vCPU, Arm",
                "memory_mb": 4096,
                "vcpus": 2,
                "disk_gb": 40,
                "prices": {"fsn1": "4.51"},
            }
        ],
        "regions": [{"slug": "fsn1", "name": "Falkenstein, DE"}],
    }


def test_the_account_lists_its_servers_priced_where_they_are() -> None:
    """Hetzner has no billing API: the servers, and no spend."""
    api = FakeAPI(
        {
            ("GET", "/servers?per_page=50"): {
                "servers": [
                    {
                        "name": "my-app",
                        "server_type": {
                            "name": "cx23",
                            "prices": [
                                {
                                    "location": "fsn1",
                                    "price_monthly": {"gross": "5.0000"},
                                },
                                {
                                    "location": "nbg1",
                                    "price_monthly": {"gross": "4.1531"},
                                },
                            ],
                        },
                        "datacenter": {"location": {"name": "nbg1"}},
                        "created": "2026-08-01T09:00:00+00:00",
                        "labels": {"managed-by": "aegis", "aegis-project": "my-app"},
                    }
                ]
            }
        }
    )
    assert HetznerClient(api).account() == {
        "servers": [
            {
                "name": "my-app",
                "size": "cx23",
                "region": "nbg1",
                "price": "4.15",
                "created": "2026-08-01T09:00:00+00:00",
                "project": "my-app",
            }
        ],
        "month_to_date": None,
        "missing": [],
    }


def test_monthly_price_rejects_unavailable_location() -> None:
    client = HetznerClient(FakeAPI(_hetzner_routes()))
    with pytest.raises(ProvisionError, match="nbg1"):
        monthly_price(client, "cx23", "ash")


def test_ensure_ssh_key_reuses_matching_key() -> None:
    routes = _hetzner_routes()
    routes[("GET", f"/ssh_keys?fingerprint={_fingerprint()}")] = {
        "ssh_keys": [{"id": 5}]
    }
    api = FakeAPI(routes)
    assert HetznerClient(api).ensure_ssh_key("my-app", PUBKEY) == (5, False)
    assert not api.called("POST", "/ssh_keys")


def test_ensure_ssh_key_creates_when_missing() -> None:
    api = FakeAPI(_hetzner_routes())
    assert HetznerClient(api).ensure_ssh_key("my-app", PUBKEY) == (11, True)


def test_create_server_sends_user_data_key_and_labels() -> None:
    api = FakeAPI(_hetzner_routes())
    server_id = HetznerClient(api).create_server(
        name="my-app", size="cx23", region="nbg1", ssh_key_id=11, user_data="#!x"
    )
    assert server_id == 42
    body = api.calls[-1][2]
    assert body is not None
    assert body["server_type"] == "cx23"
    assert body["location"] == "nbg1"
    assert body["ssh_keys"] == [11]
    assert body["user_data"] == "#!x"
    assert body["labels"]["managed-by"] == "aegis"


def test_running_ipv4_waits_for_running() -> None:
    routes = _hetzner_routes()
    client = HetznerClient(FakeAPI(routes))
    assert client.running_ipv4(42) == IP
    routes[("GET", "/servers/42")]["server"]["status"] = "initializing"
    assert client.running_ipv4(42) is None


def test_delete_server_tolerates_already_gone() -> None:
    routes = _hetzner_routes()
    routes[("DELETE", "/servers/42")] = ProvisionError("gone", status=404)
    HetznerClient(FakeAPI(routes)).delete_server(42)


def test_delete_server_raises_other_errors() -> None:
    routes = _hetzner_routes()
    routes[("DELETE", "/servers/42")] = ProvisionError("locked", status=423)
    with pytest.raises(ProvisionError):
        HetznerClient(FakeAPI(routes)).delete_server(42)


def test_cloud_init_user_data_runs_setup_script_with_home() -> None:
    data = cloud_init_user_data("#!/bin/bash\necho setup\n")
    assert data.startswith("#!/bin/bash\n")
    assert "export HOME=/root" in data
    assert "echo setup" in data


def test_cloudflare_finds_zone_by_suffix_and_creates_unproxied_record() -> None:
    api = FakeAPI(_cloudflare_routes())
    assert CloudflareDNS(api).create_a_record("app.example.com", IP) == (
        "zone1",
        "rec1",
    )
    body = api.calls[-1][2]
    assert body == {
        "type": "A",
        "name": "app.example.com",
        "content": IP,
        "ttl": 60,
        "proxied": False,
    }


def test_cloudflare_without_zone_raises() -> None:
    routes = _cloudflare_routes()
    routes[("GET", "/zones?name=example.com")] = {"result": []}
    routes[("GET", "/zones?name=com")] = {"result": []}
    with pytest.raises(ProvisionError, match="app.example.com"):
        CloudflareDNS(FakeAPI(routes)).create_a_record("app.example.com", IP)


class _FakeResponse:
    def __init__(self, status: int, data: bytes) -> None:
        self.status = status
        self.data = data


class _FakePool:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.seen: dict[str, Any] = {}

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.seen = {"method": method, "url": url, **kwargs}
        return self.response


def test_json_requester_sends_bearer_and_parses_json() -> None:
    pool = _FakePool(_FakeResponse(200, b'{"ok": true}'))
    request = json_requester("https://api.test/v1", HCLOUD, pool=pool)
    assert request("POST", "/servers", {"a": 1}) == {"ok": True}
    assert pool.seen["url"] == "https://api.test/v1/servers"
    assert pool.seen["headers"]["Authorization"] == f"Bearer {HCLOUD}"
    assert pool.seen["json"] == {"a": 1}


def test_json_requester_error_carries_api_message_not_token() -> None:
    body = b'{"error": {"code": "unauthorized", "message": "unable to authenticate"}}'
    request = json_requester(
        "https://api.test/v1", HCLOUD, pool=_FakePool(_FakeResponse(401, body))
    )
    with pytest.raises(ProvisionError) as exc:
        request("GET", "/servers")
    assert exc.value.status == 401
    assert "unable to authenticate" in str(exc.value)
    assert HCLOUD not in str(exc.value)


def test_json_requester_reads_cloudflare_errors_and_empty_bodies() -> None:
    body = b'{"success": false, "errors": [{"message": "record exists"}]}'
    request = json_requester(
        "https://cf.test", CF, pool=_FakePool(_FakeResponse(400, body))
    )
    with pytest.raises(ProvisionError, match="record exists"):
        request("POST", "/zones/z/dns_records", {})
    empty = json_requester("https://x", CF, pool=_FakePool(_FakeResponse(204, b"")))
    assert empty("DELETE", "/ssh_keys/1") == {}


def test_sslip_name_dashes_the_ip() -> None:
    assert wait.sslip_name(IP) == "203-0-113-7.sslip.io"


def test_wait_until_gives_up_after_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait.time, "sleep", lambda _s: None)
    calls: list[int] = []
    assert not wait.wait_until(lambda: calls.append(1) is not None, 3, 1)
    assert len(calls) == 3


def test_wait_for_dns_matches_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wait.time, "sleep", lambda _s: None)
    answers = iter(["198.51.100.1", IP])
    monkeypatch.setattr(wait.socket, "gethostbyname", lambda _h: next(answers))
    assert wait.wait_for_dns("app.example.com", IP, attempts=5)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my_app"\n')
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "server-setup.sh").write_text("#!/bin/bash\necho hi\n")
    (tmp_path / "id.pub").write_text(PUBKEY + "\n")
    return tmp_path


@pytest.fixture
def apis(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeAPI]:
    """Fake Hetzner + Cloudflare, no-op waits, recorded deploy hand-off."""
    fakes = {
        hetzner.API_URL: FakeAPI(_hetzner_routes()),
        digitalocean.API_URL: FakeAPI(_do_routes()),
        cmd.CLOUDFLARE_API: FakeAPI(_cloudflare_routes()),
    }
    monkeypatch.setattr(cmd, "json_requester", lambda base, _token: fakes[base])
    monkeypatch.setattr(cmd, "wait_until", lambda check, *_a, **_k: check())
    monkeypatch.setattr(cmd, "wait_for_host_key", lambda _ip: True)
    monkeypatch.setattr(cmd, "wait_for_dns", lambda _h, _ip: True)
    monkeypatch.setattr(cmd, "_cloud_init_ok", lambda _ip: True)
    deployed: list[str | None] = []
    # Each step appends to ``steps`` so a test can read the order.
    steps: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        cmd,
        "enable_tls",
        lambda root, name, email: steps.append(("tls", (root, name, email))),
    )
    monkeypatch.setattr(
        cmd,
        "deploy_command",
        lambda **kw: (
            deployed.append(kw["project_path"]),
            steps.append(("deploy", None)),
        ),
    )
    fakes["steps"] = steps  # type: ignore[assignment]
    monkeypatch.setenv("HCLOUD_TOKEN", HCLOUD)
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", DO_TOKEN)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    fakes["deployed"] = deployed  # type: ignore[assignment]
    return fakes


EMAIL = "ops@example.org"


def _provision(project: Path, *extra: str, input: str = "y\n") -> Any:
    args = ["deploy-provision", "--project-path", str(project)]
    args += ["--ssh-key", str(project / "id.pub"), "--email", EMAIL, *extra]
    return RUNNER.invoke(app, args, input=input)


def _deploy_yml(project: Path) -> dict[str, Any]:
    return yaml.safe_load((project / ".aegis" / "deploy.yml").read_text())


def test_provision_and_destroy_help() -> None:
    result = RUNNER.invoke(app, ["deploy-provision", "--help"])
    assert result.exit_code == 0
    # CI's console renders option names in colour, splitting "--provider"
    # with escape codes; read the text the user sees.
    assert "--provider" in strip_ansi_codes(result.output)
    result = RUNNER.invoke(app, ["deploy-destroy", "--help"])
    assert result.exit_code == 0


def test_provision_requires_token(
    project: Path, apis: dict[str, FakeAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HCLOUD_TOKEN")
    result = _provision(project)
    assert result.exit_code == 1
    assert "HCLOUD_TOKEN" in result.output
    assert not apis[hetzner.API_URL].calls


def test_provision_rejects_unknown_provider(
    project: Path, apis: dict[str, FakeAPI]
) -> None:
    result = _provision(project, "--provider", "linode")
    assert result.exit_code != 0
    assert not apis[hetzner.API_URL].calls


def test_provision_happy_path_sslip(project: Path, apis: dict[str, FakeAPI]) -> None:
    result = _provision(project)
    assert result.exit_code == 0, result.output
    assert "4.15" in result.output
    assert HCLOUD not in result.output
    config = _deploy_yml(project)
    assert config["server"] == {"host": IP, "user": "root", "path": "/opt/my_app"}
    assert config["domain"] == "203-0-113-7.sslip.io"
    record = config["provision"]
    assert record["provider"] == "hetzner"
    assert record["server_id"] == 42
    assert record["region"] == "nbg1"
    assert record["size"] == "cx23"
    assert record["ssh_key_id"] == 11
    assert record["status"] == "ready"
    body = next(
        c[2] for c in apis[hetzner.API_URL].calls if c[:2] == ("POST", "/servers")
    )
    assert body is not None and "echo hi" in body["user_data"]
    assert body["name"] == "my-app"
    assert apis["deployed"] == [str(project)]  # type: ignore[comparison-overlap]


def test_provision_declined_price_creates_nothing(
    project: Path, apis: dict[str, FakeAPI]
) -> None:
    result = _provision(project, input="n\n")
    assert result.exit_code == 0
    assert not apis[hetzner.API_URL].called("POST", "/servers")
    assert not (project / ".aegis" / "deploy.yml").exists()


def test_provision_with_domain_creates_cloudflare_record(
    project: Path, apis: dict[str, FakeAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", CF)
    result = _provision(project, "--domain", "app.example.com")
    assert result.exit_code == 0, result.output
    assert CF not in result.output
    config = _deploy_yml(project)
    assert config["domain"] == "app.example.com"
    assert config["provision"]["dns"] == {"zone_id": "zone1", "record_id": "rec1"}


def test_provision_domain_without_cloudflare_token_fails_before_creating(
    project: Path, apis: dict[str, FakeAPI]
) -> None:
    result = _provision(project, "--domain", "app.example.com")
    assert result.exit_code == 1
    assert "CLOUDFLARE_API_TOKEN" in result.output
    assert not apis[hetzner.API_URL].calls


def test_failure_after_create_records_server_and_keeps_it_when_declined(
    project: Path, apis: dict[str, FakeAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cmd, "wait_for_host_key", lambda _ip: False)
    result = _provision(project, input="y\nn\n")
    assert result.exit_code == 1
    assert "42" in result.output and IP in result.output
    record = _deploy_yml(project)["provision"]
    assert record["server_id"] == 42
    assert record["status"] == "provisioning"
    assert not apis[hetzner.API_URL].called("DELETE", "/servers/42")


def test_failure_after_create_deletes_when_accepted(
    project: Path, apis: dict[str, FakeAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cmd, "_cloud_init_ok", lambda _ip: False)
    result = _provision(project, input="y\ny\n")
    assert result.exit_code == 1
    hz = apis[hetzner.API_URL]
    assert hz.called("DELETE", "/servers/42")
    assert hz.called("DELETE", "/ssh_keys/11")
    assert _deploy_yml(project)["provision"]["status"] == "destroyed"


def test_unexpected_error_after_create_still_offers_cleanup(
    project: Path, apis: dict[str, FakeAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_ip: str) -> bool:
        raise OSError("ssh-keyscan missing")

    monkeypatch.setattr(cmd, "wait_for_host_key", boom)
    result = _provision(project, input="y\ny\n")
    assert isinstance(result.exception, OSError)
    assert apis[hetzner.API_URL].called("DELETE", "/servers/42")


def test_rerun_resumes_without_creating_a_second_server(
    project: Path, apis: dict[str, FakeAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cmd, "wait_for_host_key", lambda _ip: False)
    _provision(project, input="y\nn\n")
    monkeypatch.setattr(cmd, "wait_for_host_key", lambda _ip: True)
    hz = apis[hetzner.API_URL]
    hz.calls.clear()
    result = _provision(project, input="")
    assert result.exit_code == 0, result.output
    assert not hz.called("POST", "/servers")
    assert _deploy_yml(project)["provision"]["status"] == "ready"


def test_provision_refuses_when_already_ready(
    project: Path, apis: dict[str, FakeAPI]
) -> None:
    _provision(project)
    apis[hetzner.API_URL].calls.clear()
    result = _provision(project)
    assert result.exit_code == 1
    assert not apis[hetzner.API_URL].calls


def test_provision_refuses_an_open_env_before_buying_anything(
    project: Path, apis: dict[str, FakeAPI]
) -> None:
    """The deploy at its end would refuse it anyway: refused first, no
    server is bought only to sit there unconfigured."""
    (project / ".env").write_text("APP_ENV=dev\nAUTH_ENABLED=false\n")
    result = _provision(project)
    assert result.exit_code == 1
    assert "AUTH_ENABLED" in strip_ansi_codes(result.output)
    assert not apis[hetzner.API_URL].calls


def test_destroy_requires_typed_name(project: Path, apis: dict[str, FakeAPI]) -> None:
    _provision(project)
    result = RUNNER.invoke(
        app, ["deploy-destroy", "--project-path", str(project)], input="nope\n"
    )
    assert result.exit_code == 1
    assert not apis[hetzner.API_URL].called("DELETE", "/servers/42")
    assert _deploy_yml(project)["provision"]["status"] == "ready"


def test_destroy_deletes_server_dns_and_key(
    project: Path, apis: dict[str, FakeAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", CF)
    _provision(project, "--domain", "app.example.com")
    result = RUNNER.invoke(
        app, ["deploy-destroy", "--project-path", str(project)], input="my-app\n"
    )
    assert result.exit_code == 0, result.output
    assert apis[hetzner.API_URL].called("DELETE", "/servers/42")
    assert apis[hetzner.API_URL].called("DELETE", "/ssh_keys/11")
    assert apis[cmd.CLOUDFLARE_API].called("DELETE", "/zones/zone1/dns_records/rec1")
    assert _deploy_yml(project)["provision"]["status"] == "destroyed"


def test_destroy_takes_the_name_as_an_option_without_asking(
    project: Path, apis: dict[str, FakeAPI]
) -> None:
    """``--confirm`` is the typed name, for a run with nobody at the prompt
    (the Overseer's deploy agent); it must still match."""
    _provision(project)
    args = ["deploy-destroy", "--project-path", str(project), "--confirm"]
    result = RUNNER.invoke(app, [*args, "nope"])
    assert result.exit_code == 1
    assert not apis[hetzner.API_URL].called("DELETE", "/servers/42")
    result = RUNNER.invoke(app, [*args, "my-app"])
    assert result.exit_code == 0, result.output
    assert apis[hetzner.API_URL].called("DELETE", "/servers/42")


def test_destroy_without_record_fails(project: Path, apis: dict[str, FakeAPI]) -> None:
    result = RUNNER.invoke(app, ["deploy-destroy", "--project-path", str(project)])
    assert result.exit_code == 1
    assert not apis[hetzner.API_URL].calls


def _home_with_keys(tmp_path: Path, *names: str) -> Path:
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    for name in names:
        (home / ".ssh" / name).write_text(PUBKEY + "\n")
    return home


def test_without_ssh_key_the_first_existing_key_is_used(
    project: Path,
    apis: dict[str, FakeAPI],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only an RSA key on the machine: the default must not demand ed25519."""
    monkeypatch.setenv("HOME", str(_home_with_keys(tmp_path, "id_rsa.pub")))
    args = ["deploy-provision", "--project-path", str(project), "--email", EMAIL]

    result = RUNNER.invoke(app, args, input="y\n")

    assert result.exit_code == 0, result.output
    uploaded = [
        c for c in apis[hetzner.API_URL].calls if c[:2] == ("POST", "/ssh_keys")
    ]
    assert uploaded and uploaded[0][2]["public_key"] == PUBKEY


def test_without_any_ssh_key_it_says_what_it_looked_for(
    project: Path,
    apis: dict[str, FakeAPI],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(_home_with_keys(tmp_path)))
    args = ["deploy-provision", "--project-path", str(project)]

    result = RUNNER.invoke(app, args, input="y\n")

    assert result.exit_code == 1
    assert "id_ed25519.pub" in result.output and "id_rsa.pub" in result.output
    assert "--ssh-key" in result.output
    assert not apis[hetzner.API_URL].calls


def test_provision_turns_tls_on_for_the_name_before_deploying(
    project: Path, apis: dict[str, FakeAPI]
) -> None:
    """A default project has no TLS at all; the name it gets must have it."""
    result = _provision(project)

    assert result.exit_code == 0, result.output
    steps = apis["steps"]  # type: ignore[index]
    assert steps == [
        ("tls", (project, "203-0-113-7.sslip.io", EMAIL)),
        ("deploy", None),
    ]


def test_without_an_email_nothing_is_created(
    project: Path, apis: dict[str, FakeAPI]
) -> None:
    """Let's Encrypt refuses the generated placeholder address."""
    args = ["deploy-provision", "--project-path", str(project)]
    args += ["--ssh-key", str(project / "id.pub")]

    result = RUNNER.invoke(app, args, input="y\n")

    assert result.exit_code == 1
    assert "--email" in result.output
    assert not apis[hetzner.API_URL].calls


def test_the_project_email_is_used_when_it_is_real(
    project: Path, apis: dict[str, FakeAPI]
) -> None:
    (project / ".copier-answers.yml").write_text("author_email: me@real.dev\n")
    args = ["deploy-provision", "--project-path", str(project)]
    args += ["--ssh-key", str(project / "id.pub")]

    result = RUNNER.invoke(app, args, input="y\n")

    assert result.exit_code == 0, result.output
    tls = [step for step in apis["steps"] if step[0] == "tls"]  # type: ignore[index]
    assert tls[0][1][2] == "me@real.dev"


# ---------------------------------------------------------------------------
# DigitalOcean through the seam
# ---------------------------------------------------------------------------


def test_provider_digitalocean_uses_its_client_token_and_defaults(
    project: Path,
    apis: dict[str, FakeAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HCLOUD_TOKEN")
    result = _provision(project, "--provider", "digitalocean")
    assert result.exit_code == 0, result.output
    assert "12.00" in result.output and "DigitalOcean" in result.output
    assert DO_TOKEN not in result.output and HCLOUD not in result.output
    assert not apis[hetzner.API_URL].calls
    record = _deploy_yml(project)["provision"]
    assert record["provider"] == "digitalocean"
    assert (record["size"], record["region"]) == ("s-1vcpu-2gb", "tor1")
    assert (record["server_id"], record["ipv4"]) == (77, IP)
    assert (record["ssh_key_id"], record["firewall_id"]) == (21, "fw-1")
    assert _deploy_yml(project)["server"]["host"] == IP


def test_provider_digitalocean_requires_its_token(
    project: Path,
    apis: dict[str, FakeAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIGITALOCEAN_TOKEN")
    result = _provision(project, "--provider", "digitalocean")
    assert result.exit_code == 1
    assert "DIGITALOCEAN_TOKEN" in result.output
    assert not apis[digitalocean.API_URL].calls


def test_failure_after_the_firewall_lists_and_deletes_it(
    project: Path,
    apis: dict[str, FakeAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cmd, "wait_for_host_key", lambda _ip: False)
    result = _provision(project, "--provider", "digitalocean", input="y\ny\n")
    assert result.exit_code == 1
    assert "fw-1" in result.output
    do = apis[digitalocean.API_URL]
    for path in ("/firewalls/fw-1", "/droplets/77", "/account/keys/21"):
        assert do.called("DELETE", path)
    assert _deploy_yml(project)["provision"]["status"] == "destroyed"


def test_destroy_picks_the_client_from_the_record(
    project: Path,
    apis: dict[str, FakeAPI],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _provision(project, "--provider", "digitalocean")
    monkeypatch.delenv("HCLOUD_TOKEN")
    result = RUNNER.invoke(
        app, ["deploy-destroy", "--project-path", str(project)], input="my-app\n"
    )
    assert result.exit_code == 0, result.output
    do = apis[digitalocean.API_URL]
    for path in ("/firewalls/fw-1", "/droplets/77", "/account/keys/21"):
        assert do.called("DELETE", path)
    assert not apis[hetzner.API_URL].calls
