"""Where the app runs and where it can (``hosting``): the cloud a server is
on, from that cloud's own metadata service, read once per process; where
this project deploys to, from ``aegis deploy-provision``'s record; and the
providers ``aegis`` knows, with what it can do on each."""

import json
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.services.system import hosting

HETZNER = """\
availability-zone: fsn1-dc14
hostname: my-app
instance-id: 48211907
public-ipv4: 203.0.113.7
region: eu-central
"""
DROPLET = {
    "droplet_id": 512,
    "region": "nyc3",
    "interfaces": {"public": [{"ipv4": {"ip_address": "198.51.100.4"}}]},
}
EC2 = {
    "instanceId": "i-0abc",
    "instanceType": "t3.small",
    "region": "us-east-1",
    "availabilityZone": "us-east-1a",
}


def _cloud(answers: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        return answers.get(f"{request.method} {request.url.path}", httpx.Response(404))

    return httpx.MockTransport(handle)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hosting, "_running", None)


async def test_a_hetzner_server_says_so() -> None:
    transport = _cloud({"GET /hetzner/v1/metadata": httpx.Response(200, text=HETZNER)})
    found = await hosting.running_on(transport=transport)
    assert (found["key"], found["name"]) == ("hetzner", "Hetzner Cloud")
    assert dict(found["facts"]) == {
        "Location": "fsn1-dc14",
        "Server": "48211907",
        "IP": "203.0.113.7",
    }
    assert found["console"].startswith("https://console.hetzner.cloud")


async def test_a_droplet_says_so() -> None:
    transport = _cloud({"GET /metadata/v1.json": httpx.Response(200, json=DROPLET)})
    found = await hosting.running_on(transport=transport)
    assert found["key"] == "digitalocean"
    assert dict(found["facts"]) == {
        "Location": "nyc3",
        "Server": "512",
        "IP": "198.51.100.4",
    }


async def test_an_ec2_instance_says_so() -> None:
    transport = _cloud(
        {
            "PUT /latest/api/token": httpx.Response(200, text="token"),
            "GET /latest/dynamic/instance-identity/document": httpx.Response(
                200, text=json.dumps(EC2)
            ),
        }
    )
    found = await hosting.running_on(transport=transport)
    assert found["key"] == "aws"
    assert dict(found["facts"]) == {
        "Location": "us-east-1a",
        "Server": "i-0abc",
        "Type": "t3.small",
    }


@pytest.mark.parametrize(
    ("build", "name"), [("dev", "Local"), ("abc1234", "Self-hosted")]
)
async def test_no_cloud_is_local_or_self_hosted(
    monkeypatch: pytest.MonkeyPatch, build: str, name: str
) -> None:
    monkeypatch.setattr(settings, "BUILD_ID", build)
    found = await hosting.running_on(transport=_cloud({}))
    assert (found["key"], found["name"]) == (None, name)


async def test_it_asks_once_per_process() -> None:
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(404)

    await hosting.running_on(transport=httpx.MockTransport(handle))
    probes = len(asked)
    await hosting.running_on(transport=httpx.MockTransport(handle))
    assert probes and len(asked) == probes


def test_where_it_deploys_to_comes_from_the_provision_record(tmp_path: Path) -> None:
    config = tmp_path / "deploy.yml"
    config.write_text(
        "server:\n  host: 203.0.113.7\n  user: root\n"
        "provision:\n  provider: hetzner\n  server_id: 48211907\n"
        "  region: fsn1\n  size: cx22\n  domain: app.example.org\n  ipv4: 203.0.113.7\n"
    )
    found = hosting.deploys_to(config)
    assert found is not None and found["key"] == "hetzner"
    assert dict(found["facts"]) == {
        "Location": "fsn1",
        "Size": "cx22",
        "Server": "48211907",
        "Domain": "app.example.org",
        "IP": "203.0.113.7",
    }
    assert hosting.deploys_to(tmp_path / "missing.yml") is None


def test_every_provider_says_what_aegis_can_do_there() -> None:
    cards = hosting.providers(current="hetzner")
    assert [c["key"] for c in cards] == ["hetzner", "digitalocean", "aws", "server"]
    hetzner = cards[0]
    assert hetzner["current"] and "Provision" in hetzner["can"]
    assert hetzner["command"] == "aegis deploy-provision --provider hetzner"
    assert hetzner["token"] == "HCLOUD_TOKEN"
    assert hetzner["logo"] and "hetzner.com" in hetzner["logo"]
    assert not cards[1]["current"] and cards[3]["logo"] is None
