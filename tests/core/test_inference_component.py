"""The inference component: local model serving as infrastructure.

Ollama used to be one AI provider with a hidden ``ollama_mode`` question
deciding where it ran. It is now a component with two axes, the engine
(``ollama``) and where it runs (``host`` or ``docker``), declared as options
so ``inference[ollama,docker]`` parses like any bracketed plugin. The AI
service's ``ollama`` provider pulls it in; ``ollama_mode`` survives only as a
value aegis derives from the component, never asked.
"""

from typing import Any

import pytest

from aegis.constants import AnswerKeys, ComponentNames
from aegis.core.components import COMPONENTS, ComponentType
from aegis.core.option_spec import compute_auto_requires, parse_options
from aegis.core.services import SERVICES
from aegis.core.template_generator import TemplateGenerator


def test_inference_is_an_infrastructure_component() -> None:
    spec = COMPONENTS[ComponentNames.INFERENCE]
    assert spec.type is ComponentType.INFRASTRUCTURE
    assert spec.docker_services == ["ollama", "llamacpp", "kokoro-fastapi"]
    assert spec.marker_path == "app/components/inference/ollama.py"
    assert "app/components/inference" in spec.files.primary


def test_the_engine_placement_and_speech_server_parse_from_brackets() -> None:
    spec = COMPONENTS[ComponentNames.INFERENCE]
    assert parse_options("inference", spec) == {
        "engine": "ollama",
        "placement": "host",
        "speech": "none",
    }
    assert parse_options("inference[docker]", spec)["placement"] == "docker"
    assert parse_options("inference[ollama,docker,kokoro_fastapi]", spec) == {
        "engine": "ollama",
        "placement": "docker",
        "speech": "kokoro_fastapi",
    }


def test_a_speech_server_in_docker_is_a_container_of_its_own() -> None:
    """It follows the component's placement: a compose service on docker,
    the machine's own on the host."""

    def context(component: str) -> dict[str, Any]:
        return TemplateGenerator("demo", [component]).get_template_context()

    found = context("inference[docker,kokoro_fastapi]")
    assert found[AnswerKeys.INFERENCE_SPEECH] == "kokoro_fastapi"
    assert "kokoro-fastapi" in found["docker_services"]
    for elsewhere in ("inference[kokoro_fastapi]", "inference[docker]"):
        assert "kokoro-fastapi" not in context(elsewhere)["docker_services"]


def test_the_speech_server_says_where_the_app_reaches_it() -> None:
    def address(**answers: object) -> str:
        found = _render("app/core/speech_settings.py.jinja", **answers)
        return next(line for line in found.splitlines() if "SPEECH_BASE_URL:" in line)

    # Settings carry it with the component, with or without ai[voice].
    config = _render(
        "app/core/config.py.jinja",
        include_ai=False,
        ai_voice=False,
        include_inference=True,
        ollama_mode="host",
    )
    assert "    SpeechServerSettings,\n" in config

    assert address(ollama_mode="host", inference_speech="kokoro_fastapi").endswith(
        '"http://host.docker.internal:8880/v1"'
    )
    assert address(ollama_mode="docker", inference_speech="kokoro_fastapi").endswith(
        '"http://kokoro-fastapi:8880/v1"'
    )
    assert address(ollama_mode="host", inference_speech="none").endswith("= None")


def test_only_a_speech_server_in_docker_ships_a_container() -> None:
    def compose(**answers: object) -> str:
        return _render("docker-compose.yml.jinja", include_inference=True, **answers)

    assert "kokoro-fastapi:" in compose(
        ollama_mode="docker", inference_speech="kokoro_fastapi"
    )
    assert "kokoro-fastapi:" not in compose(
        ollama_mode="host", inference_speech="kokoro_fastapi"
    )
    assert "kokoro-fastapi:" not in compose(
        ollama_mode="docker", inference_speech="none"
    )


def test_the_speech_container_reports_all_it_can() -> None:
    """Overseer > Inference > Speech shows its model and its process only
    where Kokoro-FastAPI was started with the flags that open them."""
    import yaml

    found = yaml.safe_load(
        _render(
            "docker-compose.yml.jinja",
            include_inference=True,
            ollama_mode="docker",
            inference_speech="kokoro_fastapi",
        )
    )
    environment = found["services"]["kokoro-fastapi"]["environment"]
    assert environment["ALLOW_DEV_UNLOAD"] == environment["ENABLE_DEBUG_ENDPOINTS"]
    assert environment["ALLOW_DEV_UNLOAD"] == "true"


def test_the_ollama_provider_pulls_inference_in() -> None:
    ai = SERVICES["ai"]
    with_ollama = parse_options("ai[ollama,sqlite]", ai)
    assert ComponentNames.INFERENCE in compute_auto_requires(ai, with_ollama)
    without = parse_options("ai[openai]", ai)
    assert ComponentNames.INFERENCE not in compute_auto_requires(ai, without)


def test_ollama_mode_follows_the_component() -> None:
    """``ollama_mode`` is derived, never asked: the placement, or none."""
    docker = TemplateGenerator("demo", ["inference[docker]"]).get_template_context()
    assert docker[AnswerKeys.OLLAMA_MODE] == "docker"
    off = TemplateGenerator("demo", []).get_template_context()
    assert off[AnswerKeys.OLLAMA_MODE] == "none"


def test_both_axes_in_one_bracket_reach_init() -> None:
    context = TemplateGenerator(
        "demo", ["inference[ollama,docker]"]
    ).get_template_context()
    assert context[AnswerKeys.INFERENCE_PLACEMENT] == "docker"
    assert context[AnswerKeys.OLLAMA_MODE] == "docker"


def test_adding_the_component_answers_every_axis_and_ollama_mode() -> None:
    """One helper for every add path: ``aegis add inference[...]`` and the
    component ``aegis add-service ai[ollama]`` pulls in."""
    from aegis.core.components import component_option_answers

    assert component_option_answers("inference") == {
        AnswerKeys.INFERENCE_ENGINE: "ollama",
        AnswerKeys.INFERENCE_PLACEMENT: "host",
        AnswerKeys.INFERENCE_SPEECH: "none",
        AnswerKeys.OLLAMA_MODE: "host",
    }
    assert (
        component_option_answers("inference[ollama,docker]")[AnswerKeys.OLLAMA_MODE]
        == "docker"
    )
    assert component_option_answers("redis") == {}


def test_removing_the_component_resets_ollama_mode() -> None:
    reset = COMPONENTS[ComponentNames.INFERENCE].reset_answers_on_remove
    assert reset[AnswerKeys.OLLAMA_MODE] == "none"
    assert reset[AnswerKeys.INFERENCE_SPEECH] == "none"


def test_the_template_context_carries_the_component() -> None:
    context = TemplateGenerator("demo", ["inference[docker]"]).get_template_context()
    assert context[AnswerKeys.INFERENCE] == "yes"
    assert context[AnswerKeys.INFERENCE_ENGINE] == "ollama"
    assert context[AnswerKeys.INFERENCE_PLACEMENT] == "docker"
    assert "ollama" in context["docker_services"]


def test_on_the_host_there_is_no_ollama_container() -> None:
    context = TemplateGenerator("demo", ["inference"]).get_template_context()
    assert context[AnswerKeys.INFERENCE_PLACEMENT] == "host"
    assert "ollama" not in context["docker_services"]


def test_without_the_component_it_is_off() -> None:
    context = TemplateGenerator("demo", []).get_template_context()
    assert context[AnswerKeys.INFERENCE] == "no"


def _render(path: str, **overrides: object) -> str:
    from jinja2 import Environment, FileSystemLoader

    from aegis.core.component_files import get_copier_defaults, get_template_path

    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {
        **get_copier_defaults(),
        "project_slug": "demo",
        "include_ai": True,
        "ai_backend": "sqlite",
        **overrides,
    }
    return env.get_template("{{ project_slug }}/" + path).render(context)


def test_the_catalog_takes_local_models_whenever_inference_is_present() -> None:
    """Not only when Ollama is the active provider: a model pulled locally
    belongs in the picker next to the hosted ones."""
    startup = "app/components/backend/startup/llm_catalog.py.jinja"
    on = _render(startup, include_inference=True)
    assert 'source="ollama"' in on
    assert "AI_PROVIDER" not in on
    assert 'source="ollama"' not in _render(startup, include_inference=False)

    job = "app/services/ai/jobs.py.jinja"
    assert 'source="all"' in _render(job, include_inference=True)
    assert 'source="all"' not in _render(job, include_inference=False)


def test_ai_projects_keep_the_ollama_settings_where_they_were() -> None:
    """The block moved behind its own gate (inference needs it without AI),
    but an AI project renders it in the same place, blank lines and all: a
    shift would conflict in every existing project's three-way merge."""
    config = _render(
        "app/core/config.py.jinja",
        include_ai=True,
        ollama_mode="none",
        include_inference=False,
    )
    assert (
        "    COHERE_API_KEY: str | None = None\n\n    # Ollama settings (local LLM inference)\n\n"
        '    OLLAMA_BASE_URL: str = "http://localhost:11434"'
    ) in config
    assert (
        "    OLLAMA_API_KEY: str | None = None  # Optional, usually not needed\n\n"
        "    # Conversation settings\n"
    ) in config


def test_the_llamacpp_provider_pulls_in_its_engine() -> None:
    ai = SERVICES["ai"]
    brought = compute_auto_requires(ai, parse_options("ai[llamacpp,sqlite]", ai))
    assert "inference[llamacpp]" in brought
    assert "inference" not in brought


def test_llamacpp_in_docker_runs_its_own_container() -> None:
    def context(component: str) -> dict[str, Any]:
        return TemplateGenerator("demo", [component]).get_template_context()

    found = context("inference[llamacpp,docker,kokoro_fastapi]")
    assert found[AnswerKeys.INFERENCE_ENGINE] == "llamacpp"
    assert found["docker_services"][-2:] == ["llamacpp", "kokoro-fastapi"]
    assert "ollama" not in found["docker_services"]
    assert "llamacpp" not in context("inference[llamacpp]")["docker_services"]


def test_the_llamacpp_service_is_llama_server_with_the_chat_flags() -> None:
    import yaml

    found = yaml.safe_load(
        _render(
            "docker-compose.yml.jinja",
            include_inference=True,
            ollama_mode="docker",
            inference_engine="llamacpp",
        )
    )
    assert "ollama" not in found["services"]
    service = found["services"]["llamacpp"]
    assert service["image"].startswith("ghcr.io/ggml-org/llama.cpp:server")
    assert {"--jinja", "--metrics", "-np"} <= set(service["command"])
    assert "llamacpp-data" in found["volumes"]
    assert found["services"]["webserver"]["depends_on"]["llamacpp"]


def test_the_settings_name_the_engine_and_where_llama_server_is() -> None:
    """In the speech settings beside them, out of config.py's size budget."""

    def config(**answers: object) -> str:
        return _render(
            "app/core/speech_settings.py.jinja",
            include_inference=True,
            inference_engine="llamacpp",
            **answers,
        )

    assert 'INFERENCE_ENGINE: str = "llamacpp"' in config(ollama_mode="host")
    assert '"http://host.docker.internal:8080"' in config(ollama_mode="host")
    assert '"http://llamacpp:8080"' in config(
        ollama_mode="docker", inference_placement="docker"
    )


@pytest.mark.parametrize(
    ("services", "components"),
    [
        (["ai[llamacpp]"], ["inference[ollama]"]),
        (["ai[ollama]"], ["inference[llamacpp]"]),
    ],
)
def test_a_local_provider_needs_the_engine_of_its_name(
    services: list[str], components: list[str]
) -> None:
    from aegis.core.selection import SelectionError, stack_components

    with pytest.raises(SelectionError, match="engine"):
        stack_components(components, services)


def test_a_local_provider_with_its_engine_is_accepted() -> None:
    from aegis.core.selection import stack_components

    assert "inference[llamacpp,docker]" in stack_components(
        ["inference[llamacpp,docker]"], ["ai[llamacpp]"]
    )


def test_an_unnamed_engine_follows_the_local_provider() -> None:
    """The interactive flow asks only the placement: ``inference[docker]``
    beside ``ai[llamacpp]`` is llama.cpp, not the default."""
    from aegis.cli.interactive import clear_all_ai_selections, set_ai_service_config

    set_ai_service_config("ai", providers=["llamacpp"])
    try:
        context = TemplateGenerator(
            "demo",
            ["inference[docker]"],
            selected_services=["ai[pydantic-ai,sqlite,llamacpp]"],
        ).get_template_context()
    finally:
        clear_all_ai_selections()
    assert context[AnswerKeys.INFERENCE_ENGINE] == "llamacpp"
    assert "llamacpp" in context["docker_services"]


def test_adding_a_provider_keeps_the_installed_engine() -> None:
    """``aegis add-service ai[llamacpp]`` on an Ollama project is refused."""
    from aegis.core.services import local_engine_rule

    assert local_engine_rule(["llamacpp"], "ollama")
    assert local_engine_rule(["ollama", "openai"], "ollama") is None
