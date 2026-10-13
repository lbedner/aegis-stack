"""What a project's stack takes, measured where it is built, so the
Overseer can say whether a server size has room for it.

The services are production's (the compose files and profile ``aegis
deploy`` starts, ``DEPLOY_COMPOSE``), each with its memory and CPU limits
resolved as a deploy resolves them (from the env file it ships), its image
and what that image takes on disk; beside them the data volumes they keep,
and what each uses now where it runs. Asked of ``docker`` on this machine,
through ``docker`` (a callable, so tests answer for it).
"""

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .template_cleanup import env_value

Docker = Callable[..., str]
DEPLOY_COMPOSE = (
    "compose",
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.prod.yml",
)
DOCKER_SECONDS = 60
# Compose writes binary units (768M is 768 MiB); docker system df decimal
# ones (336MB); docker stats binary with an i (385.2MiB).
_UNITS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "m": 1024**2,
    "g": 1024**3,
    "t": 1024**4,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}
_SIZE = re.compile(r"\s*([\d.]+)\s*([a-zA-Z]*)\s*")
_VARIABLE = re.compile(r"\$\{(\w+)(?::?-([^}]*))?\}")


class DockerError(RuntimeError):
    """``docker`` failed; the message is its own."""


def size_of(text: str) -> int:
    """Bytes in a size as docker or compose writes it (``768M``, ``336.2MB``)."""
    found = _SIZE.fullmatch(text)
    if found is None or found.group(2).lower() not in _UNITS:
        raise ValueError(f"Not a size: {text}")
    return round(float(found.group(1)) * _UNITS[found.group(2).lower()])


def runner(root: Path) -> Docker:
    """``docker`` itself, run in ``root``; its output, or DockerError."""

    def docker(*args: str) -> str:
        try:
            done = subprocess.run(
                ["docker", *args],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=DOCKER_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DockerError(str(exc)) from None
        if done.returncode:
            raise DockerError(done.stderr.strip() or f"docker {args[0]} failed")
        return done.stdout

    return docker


def _resolver(root: Path) -> Callable[[Any], str | None]:
    """``${VAR:-default}`` as a deploy fills it: the shipped env file
    (``.env.deploy`` over ``.env``), else the default."""
    shipped = next(
        (p for p in (root / ".env.deploy", root / ".env") if p.exists()), None
    )

    def resolve(value: Any) -> str | None:
        if value is None:
            return None

        def one(found: re.Match[str]) -> str:
            given = env_value(shipped, found.group(1)) if shipped else None
            return given or found.group(2) or ""

        return _VARIABLE.sub(one, str(value)) or None

    return resolve


def _image_size(docker: Docker, image: str) -> int | None:
    """What ``image`` takes, None where it is not on this machine."""
    try:
        return int(docker("image", "inspect", "--format", "{{.Size}}", image).strip())
    except (DockerError, ValueError):
        return None


def _used(docker: Docker, project: str) -> dict[str, int]:
    """Memory each running service of ``project`` uses now, by service."""
    listed = docker(
        "ps",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--format",
        '{{.Names}}\t{{.Label "com.docker.compose.service"}}',
    )
    services = dict(line.split("\t") for line in listed.splitlines() if "\t" in line)
    if not services:
        return {}
    stats = docker(
        "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}", *services
    )
    used: dict[str, int] = {}
    for line in stats.splitlines():
        name, _, usage = line.partition("\t")
        if name in services:
            service = services[name]
            used[service] = used.get(service, 0) + size_of(usage.split("/")[0])
    return used


def measure(root: Path, docker: Docker | None = None) -> dict[str, Any]:
    """``services`` production runs (name, memory and cpus limits, None
    where unlimited; image_size; used now, None where not running here),
    the ``volumes`` they keep (name, size) and the ``images`` they need
    (bytes, each once)."""
    docker = docker or runner(root)
    config = json.loads(
        docker(
            *DEPLOY_COMPOSE,
            "--profile",
            "prod",
            "config",
            "--no-interpolate",
            "--format",
            "json",
        )
    )
    resolve = _resolver(root)
    prod = {
        name: spec
        for name, spec in config["services"].items()
        if not spec.get("profiles") or "prod" in spec["profiles"]
    }
    images = {name: resolve(spec.get("image")) for name, spec in prod.items()}
    sizes = {
        image: _image_size(docker, image) for image in set(images.values()) if image
    }
    used = _used(docker, config.get("name", root.name))
    services = []
    for name, spec in sorted(prod.items()):
        limits = (spec.get("deploy") or {}).get("resources", {}).get("limits", {})
        memory, cpus = resolve(limits.get("memory")), resolve(limits.get("cpus"))
        services.append(
            {
                "name": name,
                "memory": size_of(memory) if memory else None,
                "cpus": float(cpus) if cpus else None,
                "image_size": sizes.get(images[name] or ""),
                "used": used.get(name),
            }
        )
    kept = sorted(
        {
            v["source"]
            for spec in prod.values()
            for v in spec.get("volumes", ())
            if v.get("type") == "volume"
        }
    )
    df = json.loads(docker("system", "df", "-v", "--format", "json"))
    on_disk = {v["Name"]: size_of(v["Size"]) for v in df.get("Volumes") or ()}
    named = config.get("volumes") or {}
    volumes = [
        {"name": v, "size": on_disk.get((named.get(v) or {}).get("name", v), 0)}
        for v in kept
    ]
    total = sum(size for size in sizes.values() if size)
    return {"services": services, "volumes": volumes, "images": total}
