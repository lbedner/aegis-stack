"""
Component file tracking infrastructure.

This module provides functionality to identify which files belong to which
components by parsing the Copier template's exclusion rules.
"""

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from ..constants import AnswerKeys, ComponentNames, StorageBackends

# Constants
PROJECT_SLUG_PLACEHOLDER = "{{ project_slug }}"
JINJA_EXTENSION = ".jinja"

# Tooling/cache directories and compiled or binary artefacts that may appear
# in the template tree locally (e.g. ``__pycache__`` from importing a
# template's raw ``.py`` files). They are never authored template content,
# and the downstream renderer reads files as UTF-8 text, so a stray ``.pyc``
# crashes the walk. Skip them when expanding component directories.
_SKIP_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
_SKIP_SUFFIXES = frozenset(
    {
        # compiled python
        ".pyc",
        ".pyo",
        ".pyd",
        # images / fonts / archives that aren't UTF-8 text
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".pdf",
        ".zip",
        ".gz",
    }
)


def _is_skippable_template_file(file_path: Path) -> bool:
    """True for tooling-cache or binary files that aren't template content."""
    if any(part in _SKIP_DIRS for part in file_path.parts):
        return True
    return file_path.suffix.lower() in _SKIP_SUFFIXES


def get_template_path() -> Path:
    """Get path to Copier template directory."""
    return Path(__file__).parent.parent / "templates" / "copier-aegis-project"


def load_copier_config() -> dict[str, Any]:
    """
    Load copier.yml configuration.

    Returns:
        Dictionary containing Copier template configuration

    Raises:
        FileNotFoundError: If copier.yml doesn't exist
        yaml.YAMLError: If copier.yml is invalid
    """
    # copier.yml is now at repo root (aegis-stack/copier.yml)
    # not in the template subdirectory
    repo_root = Path(__file__).parent.parent.parent
    copier_yml = repo_root / "copier.yml"

    if not copier_yml.exists():
        raise FileNotFoundError(f"copier.yml not found at {copier_yml}")

    try:
        with open(copier_yml) as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Failed to parse copier.yml: {e}") from e


def get_copier_defaults() -> dict[str, Any]:
    """
    Extract default values for all template variables from copier.yml.

    Used by ManualUpdater to backfill missing answer keys before rendering
    templates. Without this, undefined variables like ``ollama_mode`` cause
    Jinja2 conditionals to inject unrelated component code (#504).

    Returns:
        Dictionary mapping variable names to their default values.
        Skips Jinja2-expression defaults (they depend on other variables).
        Returns empty dict if copier.yml is not available (e.g. pip install).
    """
    try:
        config = load_copier_config()
    except FileNotFoundError:
        # copier.yml lives at repo root, not inside the aegis/ package.
        # When installed via pip/uvx the file won't exist — fall back
        # gracefully so ManualUpdater behaves the same as before this fix.
        return {}

    defaults: dict[str, Any] = {}

    for key, value in config.items():
        # Skip private/internal Copier keys (e.g. _min_copier_version)
        if key.startswith("_"):
            continue

        if isinstance(value, dict) and "default" in value:
            default = value["default"]
            # Skip Jinja2 expression defaults — they depend on other variables
            # and the answers file should already have them when relevant
            if isinstance(default, str) and "{{" in default:
                continue
            defaults[key] = default

    return defaults


def parse_exclusion_pattern(pattern: str, component: str) -> str | None:
    """
    Parse a Jinja2 exclusion pattern to extract the file path for a component.

    Args:
        pattern: Jinja2 pattern like "{% if not include_scheduler %}path/to/file{% endif %}"
        component: Component name to match (e.g., "scheduler", "worker")

    Returns:
        Extracted file path, or None if pattern doesn't match the component

    Examples:
        >>> parse_exclusion_pattern(
        ...     "{% if not include_scheduler %}{{ project_slug }}/app/components/scheduler{% endif %}",
        ...     "scheduler"
        ... )
        "app/components/scheduler"

        >>> parse_exclusion_pattern(
        ...     "{% if scheduler_backend == 'memory' -%}{{ project_slug }}/app/services/scheduler{% endif %}",
        ...     "scheduler"
        ... )
        "app/services/scheduler"
    """
    # Check if pattern references this component
    if f"include_{component}" not in pattern and component not in pattern:
        return None

    # Extract path from pattern
    # Patterns look like: "{% if condition %}{{ project_slug }}/path/to/file{% endif %}"
    # We want to extract: "path/to/file"

    # Match: {% if ... %}...{{ project_slug }}/PATH{% endif %}
    match = re.search(
        r"\{%\s*if\s+.+?\s*%\}\{\{\s*project_slug\s*\}\}/(.+?)\{%\s*endif\s*%\}",
        pattern,
    )

    if match:
        # Remove any trailing wildcards or special characters
        path = match.group(1).rstrip("*")
        return path

    return None


def _expand_directories_to_files(paths: list[str]) -> list[str]:
    """
    Expand directory paths to include all nested files.

    For each directory path, recursively discover all files within it
    by scanning the template directory.

    Args:
        paths: List of file/directory paths (e.g., ["app/components/scheduler", "app/core/db.py"])

    Returns:
        Expanded list with all nested files discovered

    Example:
        >>> _expand_directories_to_files(["app/components/scheduler"])
        ["app/components/scheduler/__init__.py", "app/components/scheduler/main.py"]
    """
    template_path = get_template_path()
    expanded_paths: list[str] = []

    for path in paths:
        # Full path in template: template/{{ project_slug }}/path
        template_dir = template_path / PROJECT_SLUG_PLACEHOLDER / path

        if template_dir.exists() and template_dir.is_dir():
            # Recursively find all files in this directory
            for file_path in template_dir.rglob("*"):
                if file_path.is_file() and not _is_skippable_template_file(file_path):
                    # Convert back to relative path
                    # /path/to/template/{{ project_slug }}/app/components/scheduler/main.py.jinja
                    # -> app/components/scheduler/main.py.jinja
                    relative_path = file_path.relative_to(
                        template_path / PROJECT_SLUG_PLACEHOLDER
                    )

                    # Remove .jinja extension for the final path
                    path_str = str(relative_path)
                    if path_str.endswith(JINJA_EXTENSION):
                        path_str = path_str[: -len(JINJA_EXTENSION)]

                    expanded_paths.append(path_str)
        else:
            # Not a directory or doesn't exist - keep as-is (it's a file path)
            expanded_paths.append(path)

    return expanded_paths


def _spec_extras(component: str) -> dict[str, list[str]]:
    """Return the ``extras`` groups declared on a component/service spec."""
    from .components import COMPONENTS
    from .services import SERVICES

    spec = COMPONENTS.get(component) or SERVICES.get(component)
    return spec.files.extras if spec is not None else {}


def get_component_files(
    component: str,
    backend_variant: str | None = None,
    *,
    full: bool = False,
    answers: dict[str, Any] | None = None,
) -> list[str]:
    """
    Get list of file paths that belong to a component.

    Derived from each spec's ``FileManifest`` via
    :func:`aegis.core.post_gen_tasks.get_component_file_mapping`, so generation
    and updates stay consistent.

    The default (``full=False``) returns the *add base*: the spec's ``primary``
    files, plus scheduler persistence files for database backends
    (sqlite/postgres — the templates gate them on ``scheduler_backend !=
    "memory"``). These render real content for the chosen options, so
    ``aegis add`` never writes empty stubs.

    With ``full=True`` it returns the *complete footprint*: ``primary`` plus
    every ``extras`` group the spec owns (``ai_rag``, ``ai_voice``,
    ``scheduler_persistence``, ...). Used by ``aegis remove`` so a component is
    fully deleted regardless of which options were enabled; over-deletion is
    safe because missing paths are no-ops.

    With ``answers`` provided, extras groups whose name is a truthy answer key
    (``include_auth_org``, ``include_htmx``, ``ai_rag``, ...) join the add
    base. This is how ``aegis add`` copies option-gated files exactly when the
    project's configuration enables them — e.g. auth's org files on an
    ``auth[org]`` add, or its htmx login pages when the project ships the htmx
    frontend — instead of over-copying them from ``primary`` (issue #814).

    Args:
        component: Component name (e.g., "scheduler", "worker", "database")
        backend_variant: Optional backend variant (e.g., "memory", "sqlite") for scheduler
        full: When True, include every gated extra group (remove footprint)
        answers: Project answers; enables extras whose group name is truthy

    Returns:
        List of file paths relative to project root

    Examples:
        >>> get_component_files("scheduler")
        ['app/components/scheduler', 'app/entrypoints/scheduler.py', ...]

        >>> get_component_files("scheduler", "sqlite")
        ['app/services/scheduler', 'app/cli/tasks.py', ...]
    """
    from .post_gen_tasks import get_component_file_mapping

    mapping = get_component_file_mapping()
    base = mapping.get(component, []).copy()

    if full:
        # Remove path: complete footprint = primary + every gated extra group.
        for extra_files in _spec_extras(component).values():
            base.extend(extra_files)
        return sorted(set(_expand_directories_to_files(base)))

    if answers:
        # Option-gated extras join the add base when the project's answers
        # enable them. Groups whose name isn't an answer key (e.g.
        # ``scheduler_persistence``, handled by the backend_variant branch
        # below) simply never match.
        for group, extra_files in _spec_extras(component).items():
            if answers.get(group):
                base.extend(extra_files)

    if component == ComponentNames.SCHEDULER:
        # Scheduler persistence files are gated on ``scheduler_backend !=
        # memory``. On a database backend (sqlite/postgres) they render real
        # content (add them); on the memory backend they render empty, so
        # subtract them from the add base to avoid writing 0-byte stubs.
        persistence = mapping.get("scheduler_persistence", [])
        base_files = set(_expand_directories_to_files(base))
        persistence_files = set(_expand_directories_to_files(persistence))
        if backend_variant in (StorageBackends.SQLITE, StorageBackends.POSTGRES):
            return sorted(base_files | persistence_files)
        return sorted(base_files - persistence_files)

    # Expand directories to include all nested files
    return sorted(set(_expand_directories_to_files(base)))


def get_component_cleanup_paths(component: str) -> list[str]:
    """Return the removal footprint with directories left as directories.

    Same paths as ``get_component_files(component, full=True)`` — primary plus
    every gated extra — but *unexpanded*. That difference matters: expanding a
    directory yields only the files the template ships, so anything the project
    grew afterwards (``__pycache__``, build output such as ``static/dist/``)
    survives and keeps the directory alive. Removal wants the whole tree gone,
    which is what generation's own cleanup does.

    Args:
        component: Component or service name.

    Returns:
        Project-relative paths, each a file or a directory.
    """
    from .post_gen_tasks import get_component_file_mapping

    paths = list(get_component_file_mapping().get(component, []))
    for extra_files in _spec_extras(component).values():
        paths.extend(extra_files)
    return sorted(set(paths))


def get_service_files(service: str) -> list[str]:
    """
    Get list of file paths that belong to a service.

    Services are components that provide business logic (auth, ai).
    This is an alias for get_component_files for clarity.

    Args:
        service: Service name (e.g., "auth", "ai")

    Returns:
        List of file paths relative to project root
    """
    return get_component_files(service)


def get_all_owned_paths() -> set[str]:
    """Union of every component's and service's complete file footprint.

    A path in this set is component/service-owned: its existence in a
    project is decided by manifest membership (``aegis add``/``remove``
    copies or deletes it as a unit), not by rendering — most
    component-exclusive files carry no inline ``{% if include_x %}`` gate
    at all, since manifest membership already decides whether they're
    copied in the first place. Directories are expanded to individual
    files, and every ``extras`` group is included regardless of options
    (``full=True``, matching the removal footprint).

    This is how the render-diff engine (``aegis.core.render_diff``)
    determines which template paths are safe for it to touch — anything
    NOT in this set — without a hand-maintained registration list: the
    boundary is derived from each spec's own ``FileManifest``, which
    already exists and already lives with that spec. See aegis-stack#918.
    """
    from .components import COMPONENTS
    from .services import SERVICES

    owned: set[str] = set()
    for name in (*COMPONENTS, *SERVICES):
        owned.update(get_component_files(name, full=True))
    return owned


# Manifest-owned paths whose CONTENT also depends on other specs' answers,
# not just their own gate — ownership alone can't tell the render-diff
# engine these need touching. ``app/components/scheduler/main.py``:
# existence is scheduler-owned (only ever copied when scheduler is
# selected), but its content also registers OTHER services' jobs
# (insights, finance, ...). The old ``shared_files.py`` carried this same
# file under the "no-create" ``_REGEN_EXISTING`` policy for exactly this
# reason. A single documented exception, not a list that grows — kept
# honest by ``tests/core/test_component_ownership.py::TestOwnedButSharedPaths``
# and ``tests/core/test_render_diff_shared_scope.py``.
OWNED_BUT_SHARED_PATHS: frozenset[str] = frozenset({"app/components/scheduler/main.py"})

# Unowned by any component/service manifest (nothing claims them), but
# NOT safe for the render-diff engine to render either — the naive
# derivation would otherwise pull them into scope. Kept honest by
# ``tests/core/test_component_ownership.py``.
#
# ``.copier-answers.yml``: rendered by Copier itself with a special
# ``_copier_conf`` runtime context a bare Jinja render can't supply
# (``UndefinedError`` the first time the engine tries); it's also
# Copier's own bookkeeping file, not template content, matching its
# exclusion from the old ``INTENTIONALLY_NOT_REGENERATED`` allowlist
# ("owned by Copier itself").
#
# ``alembic/*``: not owned by any SINGLE component/service manifest
# because it's cross-cutting — materialized when ANY service needs
# migrations, removed when NONE do (``bootstrap_alembic`` /
# ``cleanup_components``'s aggregate check, Pattern C). Its static files
# (``alembic.ini`` has zero Jinja markers) render base == ours for every
# operation regardless of what changed, so the "project predates this
# file" backfill path would create a full ``alembic/`` directory the
# first time ANY component/service is added to a project that doesn't
# have it yet — even one needing no migrations at all (e.g. comms). Never
# in the old ``SHARED_TEMPLATE_FILES`` list either; existence is entirely
# the migration-bootstrap mechanism's job, not this engine's.
#
# ``.env.ports``: ships as a static placeholder comment ("Auto-generated
# by make serve") but its real content is computed and overwritten by
# ``make serve``/``poe serve`` at runtime, not by Copier rendering — it's
# gitignored and ephemeral. Static (answer-independent) and unowned, so
# the naive derivation would backfill the stub on any unrelated
# operation; its actual lifecycle belongs to the port-resolution
# scripts, not this engine.
# ``services_card.py`` / the add-model-and-migration skill: not ``.jinja``
# files at all — fully static, unowned by any manifest. Existence is
# decided by post-gen Python cleanup (``cleanup_components``: remove if
# NO services / no migrations needed) and restored on the add side by
# ``ManualUpdater._ensure_services_card``/``_ensure_migration_skill``,
# which already run right after ``_regenerate_shared_files`` in
# ``add_component`` — excluding them here is safe because those hooks
# already own creating them correctly. Confirmed live: before this
# exclusion, adding ``worker`` (unrelated to services) to a zero-service
# project incorrectly materialized ``services_card.py``. The two paths
# are defined once here (SERVICES_CARD_FILE / MIGRATION_SKILL_FILE) and
# imported by ``manual_updater``'s ensure-hooks, so the exclusion and the
# restoration mechanism can never drift apart.
# ``docs/components/api-load-testing.md`` / ``tests/services/
# test_health_logic.py``: existence gated by post-gen aggregate
# conditions (docs/components emptied when zero components selected;
# the shared integration test removed only when BOTH scheduler AND
# worker are disabled), unowned, no self-gating content. Unlike
# services_card.py there is NO existing ensure-hook restoring these when
# their condition later flips true via ``aegis add`` — but neither was
# ever in the old ``SHARED_TEMPLATE_FILES`` list either, so excluding
# them reproduces the OLD system's behavior exactly (never
# auto-restored), not a new regression. A real gap, just a pre-existing
# one; a candidate for a future ensure-hook, not solved by this
# exclusion.
# Cross-spec files with an add-side restoration hook in ManualUpdater —
# single definition shared by _ENGINE_UNSAFE_PATHS and those hooks.
SERVICES_CARD_FILE = "app/components/frontend/dashboard/cards/services_card.py"
MIGRATION_SKILL_FILE = ".claude/skills/add-model-and-migration/SKILL.md"

_ENGINE_UNSAFE_PATHS: frozenset[str] = frozenset(
    {
        AnswerKeys.ANSWERS_FILENAME,
        "alembic/alembic.ini",
        "alembic/env.py",
        "alembic/script.py.mako",
        "alembic/versions/.gitkeep",
        ".env.ports",
        SERVICES_CARD_FILE,
        MIGRATION_SKILL_FILE,
        "docs/components/api-load-testing.md",
        "tests/services/test_health_logic.py",
    }
)


def get_shared_scope(all_paths: Iterable[str]) -> list[str]:
    """Restrict ``all_paths`` (typically ``RenderDiffEngine.discover_paths()``)
    to the render-diff engine's safe scope: every path no component/service
    manifest claims, plus :data:`OWNED_BUT_SHARED_PATHS`, minus
    :data:`_ENGINE_UNSAFE_PATHS`.

    The single canonical scoping expression — callers (``ManualUpdater``,
    tests) use this rather than each re-deriving the set expression
    themselves. See aegis-stack#918/#919.
    """
    owned = get_all_owned_paths()
    candidates = set(all_paths)
    scope = (candidates - owned) | (candidates & OWNED_BUT_SHARED_PATHS)
    scope -= _ENGINE_UNSAFE_PATHS
    return sorted(scope)
