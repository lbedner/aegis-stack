"""A generated project's compose files, rendered and read as Compose reads
them: YAML with Compose's ``!override`` tag (the dev overlay's ports in
place of the base file's), which a plain YAML loader refuses. And its
entrypoint, rendered and run with stand-ins for the programs it starts."""

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!override", _Loader.construct_sequence)


def render(name: str, **overrides: Any) -> str:
    """The project file ``name`` (``docker-compose.dev.yml.jinja``) rendered
    with the copier defaults and ``overrides``."""
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {**get_copier_defaults(), "project_slug": "demo", **overrides}
    return env.get_template(f"{{{{ project_slug }}}}/{name}").render(context)


def load(text: str) -> Any:
    """``text`` (a rendered compose file) as data, ``!override`` read."""
    return yaml.load(text, Loader=_Loader)  # noqa: S506 - a SafeLoader subclass


# The programs an entrypoint may start, each stood in for by a script that
# records its call.
STUBS = ("uv", "python", "watchfiles", "taskiq", "dramatiq")


def entrypoint_calls(
    tmp_path: Path, role: list[str], env: dict[str, str], **ctx: Any
) -> list[dict]:
    """Run the entrypoint for ``role``; return each stub call in order."""
    script = tmp_path / "entrypoint.sh"
    script.write_text(render("scripts/entrypoint.sh.jinja", **ctx))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls.jsonl"
    for name in STUBS:
        stub = bin_dir / name
        stub.write_text(
            "#!/bin/bash\n"
            f'printf \'{{"cmd": "{name}", "pid": %s, "args": "%s"}}\\n\' '
            f'"$$" "$*" >> "{log}"\n'
        )
        stub.chmod(0o755)
    proc = subprocess.Popen(
        ["bash", str(script), *role],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "DOCKER_CONTAINER": "true",
            "HOME": str(tmp_path),
            **env,
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    _, err = proc.communicate(timeout=30)
    assert proc.returncode == 0, err.decode()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    for call in calls:
        call["exec"] = call["pid"] == proc.pid
    return calls
