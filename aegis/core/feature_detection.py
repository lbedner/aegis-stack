"""What an existing project has installed, read off the project itself.

One reading for every command that re-renders a project: ``aegis update``
(its dry run included) and ``aegis add`` / ``remove`` (``ManualUpdater``)
fill a question the project never answered from here, so the same project
never renders two ways.
"""

import re
from pathlib import Path
from typing import Any

from ..cli import brand
from ..constants import AnswerKeys, OllamaMode
from ..i18n import t
from .template_cleanup import env_value

# The module that registers a project's insight collectors, newest layout
# first. The older path stays so a project generated before the insights
# restructure still detects its sources when it updates.
INSIGHTS_COLLECTION_PATHS = (
    "app/services/insights/adapters/collectors/collection.py",
    "app/services/insights/collector_service.py",
)


def detect_existing_features(target_path: Path) -> dict[str, Any]:
    """Reconstruct ``include_*`` and sub-feature flags from project structure.

    Older template versions didn't have today's full set of questions in
    ``copier.yml`` (e.g. ``include_insights`` was added after 0.6.10), so
    those flags are missing from older ``.copier-answers.yml`` files.
    During ``aegis update -y``, copier silently uses the template's
    ``default: false`` for any missing flag — which means a project that
    *clearly* has ``app/services/insights/`` on disk gets re-rendered as
    if it never had insights, deleting service files and breaking the
    project.

    To prevent that, we walk the project structure and re-derive a flag
    set from what's actually installed. The caller persists those inferred
    values into ``.copier-answers.yml`` BEFORE invoking copier update, so
    copier reads them as part of the project's stored answers instead of
    falling back to template defaults for newly-added questions. Writing
    them to the answers file (rather than passing via
    ``run_update(data=...)``) means every downstream step in the same
    update run — copier render, ``cleanup_components``,
    ``sync_template_changes``, ``run_post_generation_tasks`` — sees one
    consistent picture. Earlier iterations of this fix passed the flags
    only via ``data=`` and ``cleanup_components`` then re-read the stale
    answers and deleted service files anyway.
    """
    from .components import COMPONENTS
    from .services import SERVICES

    # Marker presence → include_<name>, derived from each spec's
    # ``marker_path`` (single source of truth — a new component/service with
    # a marker is detectable on update automatically). Only ever sets True:
    # an absent marker leaves the flag out so the caller's merge doesn't
    # clobber an existing answer.
    detected: dict[str, Any] = {}
    for spec in [*SERVICES.values(), *COMPONENTS.values()]:
        if spec.marker_path and (target_path / spec.marker_path).exists():
            detected[AnswerKeys.include_key(spec.name)] = True

    # The runner was meetings' own before it was a component: a project
    # with meetings has it, though it has no answer for it and no marker
    # yet, and would otherwise render meetings without what it now imports.
    if detected.get(AnswerKeys.MEETINGS):
        detected[AnswerKeys.RUNNER] = True

    # Insights sub-flags come from the collector registration, so we
    # neither resurrect collectors the user never opted into nor tear
    # down ones they use.
    detected.update(detect_insights_sources(target_path) or {})

    # Not every question is a flag. ``ollama_mode`` is a three-valued string
    # whose answer the project states outright, in the URL it talks to.
    ollama_mode = _detect_ollama_mode(target_path)
    if ollama_mode is not None:
        detected[AnswerKeys.OLLAMA_MODE] = ollama_mode
        # Ollama is the inference component now: a project that talks to one
        # has it, at the placement its URL says.
        detected[AnswerKeys.INFERENCE] = True
        detected[AnswerKeys.INFERENCE_PLACEMENT] = ollama_mode

    detected.update(_detect_finance_providers(target_path))

    return detected


def with_detected_features(
    target_path: Path, answers: dict[str, Any]
) -> dict[str, Any]:
    """The answers ``aegis update`` renders from: :func:`fill_answers` over
    what :func:`detect_existing_features` reads off the project."""
    return fill_answers(answers, detect_existing_features(target_path))


def fill_answers(answers: dict[str, Any], detected: dict[str, Any]) -> dict[str, Any]:
    """``answers`` with each ``detected`` flag the project never answered,
    and each component an installed part requires switched on, warning with
    both names.

    The one reading ``aegis update`` and ``aegis add`` / ``remove`` share.
    Only a missing answer is filled: an explicit ``False`` from a user who
    deliberately removed a service stands, unless a part still installed
    requires it.
    """
    filled = {**answers, **{k: v for k, v in detected.items() if k not in answers}}
    for part, required in enable_required_components(filled):
        brand.warn(t("update.requirement_enabled", part=part, required=required))
    return filled


def enable_required_components(answers: dict[str, Any]) -> list[tuple[str, str]]:
    """Switch on, in ``answers``, each component an installed part requires.

    The requirements are the ones init and add resolve, from the same
    resolvers: a service's components plus what its chosen options bring
    (``ai[sqlite]`` needs a database), a component's transitively. Returns
    the ``(part, required)`` pairs it switched on, for the caller to report.
    """
    from .components import COMPONENTS, CORE_COMPONENTS
    from .services import SERVICES

    enabled: list[tuple[str, str]] = []
    for spec in [*SERVICES.values(), *COMPONENTS.values()]:
        if answers.get(AnswerKeys.include_key(spec.name)) is not True:
            continue
        for required in sorted(_required_by(spec, answers) - {spec.name}):
            key = AnswerKeys.include_key(required)
            if required in CORE_COMPONENTS or answers.get(key) is True:
                continue
            answers[key] = True
            enabled.append((spec.name, required))
    return enabled


def _required_by(spec: Any, answers: dict[str, Any]) -> set[str]:
    """Base names of every component ``spec``, as the project answered its
    options, requires, transitively."""
    from .component_utils import extract_base_component_name
    from .dependency_resolver import DependencyResolver
    from .service_resolver import ServiceResolver
    from .services import SERVICES

    if spec.name in SERVICES:
        resolved, _ = ServiceResolver.resolve_service_dependencies(
            [_installed_spec_string(spec, answers)]
        )
    else:
        resolved = DependencyResolver.resolve_dependencies([spec.name])
    return {extract_base_component_name(c) for c in resolved}


def _installed_spec_string(spec: Any, answers: dict[str, Any]) -> str:
    """The bracket request (``ai[pydantic-ai,sqlite,openai]``) naming the
    options the project holds; an answer that is not one of an option's
    choices is left to its default, as the resolver would."""
    from .option_spec import OptionMode, multi_values

    values: list[str] = []
    for opt in spec.options:
        if opt.answer_key is None:
            continue
        current = answers.get(opt.answer_key)
        if opt.mode is OptionMode.MULTI:
            values += [v for v in multi_values(current) if v in opt.choices]
        elif opt.mode is OptionMode.FLAG:
            values += opt.choices[:1] if current is True else []
        elif current in opt.choices:
            values.append(current)
    return f"{spec.name}[{','.join(values)}]" if values else spec.name


def detect_insights_sources(project_path: Path) -> dict[str, bool] | None:
    """Which insight sources the project has wired up, by sub-flag key.

    The collector files alone are no signal: older templates shipped
    them all unconditionally. What counts is whether the collection
    module registers the collector. None when the project has no
    insights service.
    """
    for rel in INSIGHTS_COLLECTION_PATHS:
        path = project_path / rel
        if not path.is_file():
            continue
        src = path.read_text()
        return {
            AnswerKeys.INSIGHTS_GITHUB: "GitHubTrafficCollector" in src,
            AnswerKeys.INSIGHTS_PYPI: "PyPICollector" in src,
            AnswerKeys.INSIGHTS_PLAUSIBLE: "PlausibleCollector" in src,
            AnswerKeys.INSIGHTS_REDDIT: "RedditCollector" in src,
        }
    return None


def _detect_finance_providers(target_path: Path) -> dict[str, bool]:
    """The finance provider flags, read back off the project's own settings.

    ``config.py`` carries these two answers verbatim — copier renders
    ``FINANCE_PLAID: bool = True`` or ``False`` — so the project states them
    outright and there is nothing to infer. A field that is absent (the
    project has no finance service, or predates the field) is left out
    rather than guessed.
    """
    config = target_path / "app" / "core" / "config.py"
    if not config.is_file():
        return {}
    source = config.read_text()
    detected: dict[str, bool] = {}
    for field, answer_key in (
        ("FINANCE_PLAID", AnswerKeys.FINANCE_PLAID),
        ("FINANCE_SNAPTRADE", AnswerKeys.FINANCE_SNAPTRADE),
    ):
        match = re.search(rf"^\s+{field}: bool = (True|False)$", source, re.M)
        if match:
            detected[answer_key] = match.group(1) == "True"
    return detected


def _detect_ollama_mode(target_path: Path) -> str | None:
    """Which Ollama the project talks to, from the URL it actually uses.

    The template's own dichotomy: ``docker`` is the compose service, and any
    other reachable URL is an Ollama the project talks to over the network,
    which is ``host``. An unset variable means no Ollama, which is already
    the default — return None so nothing is written and no stored answer is
    clobbered.

    ``.env`` is what the app reads; ``.env.example`` is the template artifact
    it was seeded from, and only stands in when the real file is gone.
    """
    for name in (".env", ".env.example"):
        url = env_value(target_path / name, "OLLAMA_BASE_URL")
        if url is None:
            continue
        return OllamaMode.DOCKER if "//ollama:" in url else OllamaMode.HOST
    return None
