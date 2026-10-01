"""The inference component: local model serving as infrastructure.

Ollama used to be one AI provider with a hidden ``ollama_mode`` question
deciding where it ran. It is now a component with two axes, the engine
(``ollama``) and where it runs (``host`` or ``docker``), declared as options
so ``inference[ollama,docker]`` parses like any bracketed plugin. The AI
service's ``ollama`` provider pulls it in; ``ollama_mode`` survives only as a
value aegis derives from the component, never asked.
"""

from aegis.constants import AnswerKeys, ComponentNames
from aegis.core.components import COMPONENTS, ComponentType
from aegis.core.option_spec import compute_auto_requires, parse_options
from aegis.core.services import SERVICES
from aegis.core.template_generator import TemplateGenerator


def test_inference_is_an_infrastructure_component() -> None:
    spec = COMPONENTS[ComponentNames.INFERENCE]
    assert spec.type is ComponentType.INFRASTRUCTURE
    assert spec.docker_services == ["ollama"]
    assert spec.marker_path == "app/components/inference/ollama.py"
    assert "app/components/inference" in spec.files.primary


def test_the_engine_and_placement_parse_from_brackets() -> None:
    spec = COMPONENTS[ComponentNames.INFERENCE]
    assert parse_options("inference", spec) == {"engine": "ollama", "placement": "host"}
    assert parse_options("inference[docker]", spec)["placement"] == "docker"
    assert parse_options("inference[ollama,docker]", spec) == {
        "engine": "ollama",
        "placement": "docker",
    }


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
