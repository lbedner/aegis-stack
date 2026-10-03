"""Comma lists keep commas inside brackets: ``inference[ollama,docker]`` is one item.

``init --components`` and every command reading a list through
``parse_comma_separated_list`` (add, remove, remove-service) split on every
comma, so a multi-value option crashed before any work started.
"""

from pathlib import Path

import pytest
import typer

from aegis.cli.validation import parse_comma_separated_list
from tests.cli.conftest import GenerationCalls
from tests.cli.test_utils import run_aegis_command


def test_a_comma_inside_brackets_does_not_split_the_item() -> None:
    assert parse_comma_separated_list(
        "inference[ollama,docker],worker[taskiq]", "component"
    ) == ["inference[ollama,docker]", "worker[taskiq]"]


def test_an_empty_item_is_still_refused() -> None:
    with pytest.raises(typer.Exit):
        parse_comma_separated_list("redis,,worker", "component")


def test_init_takes_a_multi_value_component_option(
    init_without_generation: GenerationCalls, tmp_path: Path
) -> None:
    result = run_aegis_command(
        "init",
        "bracket-app",
        "--components",
        "inference[ollama,docker],worker[taskiq]",
        "--output-dir",
        str(tmp_path),
        "--no-interactive",
        "--yes",
    )

    assert result.success, result.stderr + result.stdout
    ((template_gen, _),) = init_without_generation
    answers = template_gen.option_answers()
    assert answers["inference_placement"] == "docker"
    assert answers["inference_engine"] == "ollama"


def test_init_takes_payment_with_its_provider_spelled_out(
    init_without_generation: GenerationCalls, tmp_path: Path
) -> None:
    result = run_aegis_command(
        "init",
        "pay-app",
        "--services",
        "payment[stripe]",
        "--output-dir",
        str(tmp_path),
        "--no-interactive",
        "--yes",
    )

    assert result.success, result.stderr + result.stdout
    ((template_gen, _),) = init_without_generation
    context = template_gen.get_template_context()
    assert context["include_payment"] == "yes"
    assert context["payment_provider"] == "stripe"


def test_an_unknown_payment_provider_names_the_valid_ones(
    init_without_generation: GenerationCalls, tmp_path: Path
) -> None:
    result = run_aegis_command(
        "init",
        "pay-app",
        "--services",
        "payment[paypal]",
        "--output-dir",
        str(tmp_path),
        "--no-interactive",
        "--yes",
    )

    assert not result.success
    assert "stripe" in result.stderr + result.stdout


def test_a_malformed_component_is_refused_without_a_traceback(
    init_without_generation: GenerationCalls, tmp_path: Path
) -> None:
    result = run_aegis_command(
        "init",
        "bad-app",
        "--components",
        "redis[",
        "--output-dir",
        str(tmp_path),
        "--no-interactive",
        "--yes",
    )

    assert not result.success
    assert "Invalid component name format" in result.stderr + result.stdout
