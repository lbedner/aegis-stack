"""The deploy component: where the app runs, with the target as its axis.

``deploy[compose]`` (the default, and the only value until ECS) puts a
socket proxy in the compose files: the one container that mounts the
Docker socket, answering only the reads the Overseer needs, over a Unix
socket in a shared volume so it has no network at all.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.constants import AnswerKeys, ComponentNames
from aegis.core.component_files import get_copier_defaults, get_template_path
from aegis.core.components import COMPONENTS, ComponentType, component_option_answers
from aegis.core.template_generator import TemplateGenerator

PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
DOCKER_SOCKET = "/var/run/docker.sock"
PROXY_SOCKET = "/var/run/docker-proxy/docker.sock"


def _compose(**overrides: Any) -> dict[str, Any]:
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {**get_copier_defaults(), "project_slug": "demo", **overrides}
    rendered = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/docker-compose.yml.jinja"
    ).render(context)
    return yaml.safe_load(rendered)


def _allowed_get(proxy: dict[str, Any]) -> re.Pattern[str]:
    """The proxy's GET allowlist, anchored the way the proxy anchors it."""
    (flag,) = [a for a in proxy["command"] if a.startswith("-allowGET=")]
    return re.compile(f"^{flag.removeprefix('-allowGET=')}$")


def test_deploy_is_an_optional_infrastructure_component() -> None:
    spec = COMPONENTS[ComponentNames.DEPLOY]
    assert spec.type is ComponentType.INFRASTRUCTURE
    assert spec.docker_services == ["socket-proxy"]
    assert spec.marker_path in spec.files.primary
    assert ComponentNames.DEPLOY in ComponentNames.INFRASTRUCTURE_ORDER


def test_the_target_axis_defaults_to_compose() -> None:
    assert component_option_answers("deploy") == {AnswerKeys.DEPLOY_TARGET: "compose"}
    assert component_option_answers("deploy[compose]") == {
        AnswerKeys.DEPLOY_TARGET: "compose"
    }
    with pytest.raises(ValueError):
        component_option_answers("deploy[kubernetes]")


def test_the_context_carries_it() -> None:
    context = TemplateGenerator("demo", ["deploy"]).get_template_context()
    assert context[AnswerKeys.DEPLOY] == "yes"
    assert context[AnswerKeys.DEPLOY_TARGET] == "compose"
    without = TemplateGenerator("demo", []).get_template_context()
    assert without[AnswerKeys.DEPLOY] == "no"


def test_without_it_there_is_no_proxy() -> None:
    compose = _compose()
    assert "socket-proxy" not in compose["services"]
    assert "docker-proxy" not in (compose.get("volumes") or {})


def test_only_the_proxy_mounts_the_docker_socket() -> None:
    compose = _compose(include_deploy=True, deploy_target="compose")
    mounting = sorted(
        name
        for name, svc in compose["services"].items()
        if any(str(m).startswith(f"{DOCKER_SOCKET}:") for m in svc.get("volumes", []))
    )
    assert mounting == ["socket-proxy"]


def test_the_proxy_has_no_network_and_no_privileges() -> None:
    proxy = _compose(include_deploy=True, deploy_target="compose")["services"][
        "socket-proxy"
    ]
    assert proxy["network_mode"] == "none"
    assert proxy["read_only"] is True
    assert proxy["cap_drop"] == ["ALL"]
    assert f"-proxysocketendpoint={PROXY_SOCKET}" in proxy["command"]
    assert set(proxy["profiles"]) == {"dev", "prod"}


@pytest.mark.parametrize(
    "path",
    [
        "/containers/json",
        "/v1.47/containers/json",
        "/v1.47/containers/demo-webserver-1/stats",
        "/v1.47/containers/demo-webserver-1/logs",
        "/v1.47/info",
        "/v1.47/system/df",
    ],
)
def test_the_proxy_answers_the_reads(path: str) -> None:
    proxy = _compose(include_deploy=True)["services"]["socket-proxy"]
    assert _allowed_get(proxy).match(path)


@pytest.mark.parametrize(
    "path",
    [
        # Inspect returns a container's whole Env, for any container on the
        # host: the proxy cannot scope by project, so it is refused outright.
        "/v1.47/containers/abc123/json",
        "/containers/demo-webserver-1/json",
        "/v1.47/containers/abc123/export",
        "/v1.47/containers/abc123/archive",
        "/v1.47/containers/abc123/top",
        "/v1.47/images/json",
        "/v1.47/volumes",
        "/v1.47/secrets",
        "/v1.47/events",
        "/v1.47/containers/a/../../images/json",
    ],
)
def test_the_proxy_refuses_everything_else(path: str) -> None:
    proxy = _compose(include_deploy=True)["services"]["socket-proxy"]
    assert not _allowed_get(proxy).match(path)


def test_the_first_cut_allows_no_writes() -> None:
    proxy = _compose(include_deploy=True)["services"]["socket-proxy"]
    allows = [a.split("=", 1)[0] for a in proxy["command"] if a.startswith("-allow")]
    assert set(allows) <= {"-allowGET", "-allowhealthcheck"}


def test_every_app_container_reaches_the_proxy_socket() -> None:
    compose = _compose(include_deploy=True, include_worker=True, include_redis=True)
    image = compose["x-app"]["image"]
    for name, svc in compose["services"].items():
        if svc.get("image") == image:
            assert "docker-proxy:/var/run/docker-proxy" in svc["volumes"], name
    assert "docker-proxy" in compose["volumes"]


def test_the_image_carries_the_build_id_as_a_label() -> None:
    """The runtime reads the build from a label, never from a container's
    Env (inspect is refused): ``aegis deploy`` stamps ``BUILD_ID`` into the
    server's ``.env``, compose passes it as a build arg, the image labels it."""
    compose = _compose()
    assert "BUILD_ID=${BUILD_ID:-dev}" in compose["x-app"]["build"]["args"]
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    dockerfile = env.get_template(
        f"{PROJECT_SLUG_PLACEHOLDER}/Dockerfile.jinja"
    ).render({**get_copier_defaults(), "project_slug": "demo"})
    assert "ARG BUILD_ID=dev" in dockerfile
    assert 'org.opencontainers.image.revision="${BUILD_ID}"' in dockerfile
