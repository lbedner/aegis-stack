"""DigitalOcean behind the provider seam, and the one provider table.

Every call goes through ``FakeAPI``; nothing reaches a real DigitalOcean
account.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aegis.core.provision import digitalocean, hetzner
from aegis.core.provision.digitalocean import DigitalOceanClient
from aegis.core.provision.http import ProvisionError, json_requester
from aegis.core.provision.registry import FACTS, PROVIDERS
from tests.cli.test_deploy_provision import (
    DO_TOKEN,
    IP,
    PUBKEY,
    FakeAPI,
    _do_routes,
    _FakePool,
    _FakeResponse,
    _fingerprint,
)


def _client(routes: dict[tuple[str, str], Any] | None = None) -> DigitalOceanClient:
    return DigitalOceanClient(FakeAPI(routes or _do_routes()))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


def test_monthly_price_reads_the_size_list() -> None:
    assert _client().monthly_price("s-1vcpu-2gb", "nyc3") == "12.00"


def test_monthly_price_rejects_a_region_the_size_is_not_in() -> None:
    with pytest.raises(ProvisionError, match="nyc3, fra1"):
        _client().monthly_price("s-1vcpu-2gb", "sgp1")


def test_monthly_price_rejects_an_unknown_size() -> None:
    with pytest.raises(ProvisionError, match="s-9vcpu"):
        _client().monthly_price("s-9vcpu", "nyc3")


def test_ensure_ssh_key_reuses_the_key_with_this_fingerprint() -> None:
    routes = _do_routes()
    routes[("GET", f"/account/keys/{_fingerprint()}")] = {"ssh_key": {"id": 5}}
    api = FakeAPI(routes)
    assert DigitalOceanClient(api).ensure_ssh_key("my-app", PUBKEY) == (5, False)
    assert not api.called("POST", "/account/keys")


def test_ensure_ssh_key_uploads_on_404() -> None:
    api = FakeAPI(_do_routes())
    assert DigitalOceanClient(api).ensure_ssh_key("my-app", PUBKEY) == (21, True)
    body = api.calls[-1][2]
    assert body is not None and body["public_key"] == PUBKEY
    assert body["name"].startswith("aegis-my-app-")


def test_ensure_ssh_key_raises_other_lookup_errors() -> None:
    routes = _do_routes()
    routes[("GET", f"/account/keys/{_fingerprint()}")] = ProvisionError(
        "denied", status=403
    )
    with pytest.raises(ProvisionError, match="denied"):
        _client(routes).ensure_ssh_key("my-app", PUBKEY)


def test_create_server_sends_image_user_data_key_and_tags() -> None:
    api = FakeAPI(_do_routes())
    server_id = DigitalOceanClient(api).create_server(
        name="my-app", size="s-1vcpu-2gb", region="nyc3", ssh_key_id=21, user_data="#!x"
    )
    assert server_id == 77
    body = api.calls[-1][2]
    assert body is not None
    assert body["image"] == "ubuntu-24-04-x64"
    assert (body["size"], body["region"]) == ("s-1vcpu-2gb", "nyc3")
    assert body["ssh_keys"] == [21]
    assert body["user_data"] == "#!x"
    assert "aegis-project:my-app" in body["tags"]


def test_running_ipv4_is_the_public_address_once_active() -> None:
    routes = _do_routes()
    assert _client(routes).running_ipv4(77) == IP
    routes[("GET", "/droplets/77")] = {
        "droplet": {"id": 77, "status": "new", "networks": {"v4": []}}
    }
    assert _client(routes).running_ipv4(77) is None


def test_firewall_opens_ssh_http_https_only_and_attaches_to_the_droplet() -> None:
    api = FakeAPI(_do_routes())
    assert DigitalOceanClient(api).create_firewall("my-app", 77) == "fw-1"
    body = api.calls[-1][2]
    assert body is not None
    assert body["droplet_ids"] == [77]
    inbound = {(r["protocol"], r["ports"]) for r in body["inbound_rules"]}
    assert inbound == {("tcp", "22"), ("tcp", "80"), ("tcp", "443")}
    assert {r["protocol"] for r in body["outbound_rules"]} == {"tcp", "udp", "icmp"}


@pytest.mark.parametrize(
    ("delete", "path"),
    [
        ("delete_server", "/droplets/77"),
        ("delete_ssh_key", "/account/keys/21"),
        ("delete_firewall", "/firewalls/fw-1"),
    ],
)
def test_deletes_tolerate_already_gone(delete: str, path: str) -> None:
    routes = _do_routes()
    routes[("DELETE", path)] = ProvisionError("gone", status=404)
    target = path.rsplit("/", 1)[1]
    getattr(_client(routes), delete)(int(target) if target.isdigit() else target)


def test_json_requester_reads_digitalocean_top_level_message() -> None:
    body = b'{"id": "unauthorized", "message": "Unable to authenticate you"}'
    request = json_requester(
        digitalocean.API_URL, DO_TOKEN, pool=_FakePool(_FakeResponse(401, body))
    )
    with pytest.raises(ProvisionError, match="Unable to authenticate you"):
        request("GET", "/droplets/1")


# ---------------------------------------------------------------------------
# The one provider table
# ---------------------------------------------------------------------------


def test_registry_is_the_overseer_table_and_every_provisioner_has_a_client() -> None:
    table = json.loads(FACTS.read_text())
    provisioners = {p["key"] for p in table if "Provision" in p["can"]}
    assert set(PROVIDERS) == provisioners == {"hetzner", "digitalocean"}
    assert FACTS.parts[-4:] == ("app", "services", "system", "providers.json")


def test_each_provider_knows_its_token_and_defaults() -> None:
    do, hz = PROVIDERS["digitalocean"], PROVIDERS["hetzner"]
    assert (do.token_env, do.size, do.region) == (
        "DIGITALOCEAN_TOKEN",
        "s-1vcpu-2gb",
        "nyc3",
    )
    assert (hz.token_env, hz.size, hz.region) == ("HCLOUD_TOKEN", "cx23", "nbg1")
    assert (do.api_url, hz.api_url) == (digitalocean.API_URL, hetzner.API_URL)
