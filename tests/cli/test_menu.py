"""The generator's menu (``aegis menu``) and its check of a selection
(``aegis.core.selection``): what the menu accepts is a command ``init``
accepts, what it refuses ``init`` refuses for the same rule, and the text
listings say what the JSON says."""

import json
import re
import shlex
from pathlib import Path

import pytest

from aegis.blueprints import BLUEPRINTS, blueprint_selection
from aegis.core.components import COMPONENTS
from aegis.core.menu import menu
from aegis.core.selection import SelectionError, init_command_for
from aegis.core.services import SERVICES

from .test_utils import run_aegis_command


def _flags(command: str) -> dict[str, str]:
    """``--components``/``--services`` of an init command."""
    words = shlex.split(command)
    return {
        flag[2:]: words[i + 1]
        for i, flag in enumerate(words)
        if flag in ("--components", "--services")
    }


def test_the_menu_lists_every_part_with_what_its_brackets_take() -> None:
    data = json.loads(run_aegis_command("menu").stdout)
    assert [p["name"] for p in data["components"]] == list(COMPONENTS)
    assert [p["name"] for p in data["services"]] == list(SERVICES)
    database = next(p for p in data["components"] if p["name"] == "database")
    assert database["options"][0]["choices"] == ["sqlite", "postgres", "neon"]
    ai = next(p for p in data["services"] if p["name"] == "ai")
    assert {o["name"] for o in ai["options"]} >= {"framework", "backend", "providers"}


@pytest.mark.parametrize("slug", sorted(BLUEPRINTS))
def test_an_accepted_selection_yields_a_command_that_rebuilds_it(slug: str) -> None:
    picked = blueprint_selection(BLUEPRINTS[slug])
    command = init_command_for(
        "demo", ",".join(picked.components) or None, ",".join(picked.services) or None
    )
    flags = _flags(command)
    # Every component it brings spelled out, so the command checks again
    # with --components given and comes back the same stack.
    again = _flags(
        init_command_for("demo", flags.get("components"), flags.get("services"))
    )
    assert set(again["components"].split(",")) == set(flags["components"].split(","))
    assert again.get("services") == flags.get("services")


def test_a_selection_comes_back_with_what_it_brings() -> None:
    command = init_command_for("demo", "worker[taskiq],scheduler[sqlite]", "ai[sqlite]")
    components = _flags(command)["components"].split(",")
    assert {"redis", "database[sqlite]", "worker[taskiq]"} <= set(components)


@pytest.mark.parametrize(
    ("components", "services", "rule"),
    [
        ("database[mysql]", None, "Unknown value 'mysql' in database[...]"),
        ("worker[celery]", None, "Unknown value 'celery' in worker[...]"),
        ("nonsense", None, "Unknown component: nonsense"),
        (None, "nonsense", "Unknown services: nonsense"),
        ("redis[", None, "Invalid component name format"),
        ("scheduler[sqlite],database[postgres]", None, "scheduler"),
        (None, "ai[bogus]", "Invalid ai service syntax"),
        (None, "insights[per_user]", "requires service 'auth'"),
        ("redis", "auth", "Service 'auth' requires component 'database'"),
    ],
)
def test_init_refuses_what_the_menu_refuses_for_the_same_rule(
    components: str | None, services: str | None, rule: str, tmp_path: Path
) -> None:
    with pytest.raises(SelectionError) as refused:
        init_command_for("demo", components, services)
    assert any(rule in r for r in refused.value.rules)

    args = ["demo", "--no-interactive", "--yes", "--output-dir", str(tmp_path)]
    args += ["--components", components] if components else []
    args += ["--services", services] if services else []
    result = run_aegis_command("init", *args)
    assert result.returncode == 1
    assert rule in re.sub(r"\s+", " ", result.stdout + result.stderr)


def test_a_refusal_names_what_would_satisfy_it() -> None:
    with pytest.raises(SelectionError) as refused:
        init_command_for("demo", "redis", "auth")
    assert "database" in refused.value.missing


def test_a_name_init_refuses_is_refused() -> None:
    with pytest.raises(SelectionError):
        init_command_for("aegis", None, "auth")


@pytest.mark.parametrize("kind", ["components", "services"])
def test_the_text_listing_says_what_the_json_says(kind: str) -> None:
    text = run_aegis_command(kind).stdout
    for part in menu()[kind]:
        if part["group"] == "core":
            continue
        assert re.search(rf"^\s+{re.escape(part['name'])}\s+- ", text, re.M), part
        for dep in part["requires"]:
            assert dep in text, (part["name"], dep)
