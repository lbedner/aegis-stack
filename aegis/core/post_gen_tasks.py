"""
Shared post-generation tasks for Cookiecutter and Copier.

This module provides common post-generation functionality used by both
template engines to avoid code duplication and ensure consistent behavior.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import typer

from aegis.constants import (
    AIFrameworks,
    AnswerKeys,
    StorageBackends,
    WorkerBackends,
)
from aegis.core.build_reporter import BuildReporter
from aegis.core.components import COMPONENTS, ComponentType
from aegis.core.file_manifest import (
    apply_cleanup_path,
    compute_file_mapping,
    iter_cleanup_paths,
)
from aegis.core.project_map import render_project_map
from aegis.core.services import SERVICES
from aegis.core.template_cleanup import run_resilient
from aegis.i18n import t

from ..cli import brand

# Task configuration constants (following tests/cli/test_utils.py pattern)
POST_GEN_TIMEOUT_INSTALL = 300  # 5 minutes for dependency installation
POST_GEN_TIMEOUT_FORMAT = 60  # 1 minute for code formatting
POST_GEN_TIMEOUT_MIGRATION = 30  # 30 seconds for database migration
POST_GEN_TIMEOUT_LLM_SYNC = 90  # 90 seconds for LLM catalog sync
POST_GEN_STDERR_MAX_LINES = 15  # Maximum stderr lines to display


def _truncate_stderr(stderr: str, max_lines: int = POST_GEN_STDERR_MAX_LINES) -> str:
    """
    Truncate stderr output to a reasonable number of lines.

    Args:
        stderr: The stderr output to truncate
        max_lines: Maximum number of lines to show

    Returns:
        Truncated stderr with indication if lines were omitted
    """
    lines = stderr.strip().split("\n")
    if len(lines) <= max_lines:
        return stderr.strip()

    # Show first and last portions
    head_lines = max_lines // 2
    tail_lines = max_lines - head_lines
    omitted = len(lines) - max_lines

    result = lines[:head_lines]
    result.append(f"   ... ({omitted} lines omitted) ...")
    result.extend(lines[-tail_lines:])
    return "\n".join(result)


def get_component_file_mapping() -> dict[str, list[str]]:
    """Map each component/service to the files it owns.

    Derived from each spec's ``FileManifest`` — the single source of truth.
    ``mapping[name]`` is the spec's ``primary`` add base, and every ``extras``
    group is emitted under its own key (e.g. ``scheduler_persistence``,
    ``ai_rag``, ``ai_voice``) for the option/variant-gated consumers. The full
    add/remove footprint (``primary`` plus every extra) is assembled by
    :func:`aegis.core.component_files.get_component_files`.

    Returns:
        Dict mapping component/service (and extra) names to file paths
        relative to the project root.
    """
    return compute_file_mapping([*COMPONENTS.values(), *SERVICES.values()])


def remove_file(project_path: Path, filepath: str) -> None:
    """
    Remove a file from the generated project.

    Args:
        project_path: Path to the project directory
        filepath: Relative path to the file to remove
    """
    full_path = project_path / filepath
    if full_path.exists():
        full_path.unlink()


def remove_dir(project_path: Path, dirpath: str) -> None:
    """
    Remove a directory from the generated project.

    Args:
        project_path: Path to the project directory
        dirpath: Relative path to the directory to remove
    """
    full_path = project_path / dirpath
    if full_path.exists():
        shutil.rmtree(full_path)


def cleanup_worker_backend_files(project_path: Path, worker_backend: str) -> None:
    """Resolve worker backend variant files to canonical names (Pattern D).

    Worker backend variants ship as sibling files (``pools_dramatiq.py``,
    ``queues/system_taskiq.py``, ...). For the chosen backend the variants
    are renamed onto the canonical names; every other backend's files are
    removed. Shared by init (``cleanup_components``) and the add path
    (``ManualUpdater.add_component``) — without this the add path leaves
    arq code at the canonical names with the variants strewn alongside.

    Args:
        project_path: Path to the generated project
        worker_backend: Chosen backend (``arq``, ``taskiq``, or ``dramatiq``)
    """
    queues_dir = project_path / "app/components/worker/queues"
    worker_dir = project_path / "app/components/worker"
    api_dir = project_path / "app/components/backend/api"
    services_dir = project_path / "app/services"
    lt_worker_dir = project_path / "app/services/load_test/worker"

    # Helper: remove all files matching a suffix pattern
    def _remove_backend_files(suffix: str) -> None:
        """Remove all files with the given backend suffix."""
        for f in queues_dir.glob(f"*{suffix}"):
            f.unlink()
        for name in [
            f"middleware{suffix}",
            f"pools{suffix}",
            f"registry{suffix}",
            f"broker{suffix}",
        ]:
            target = worker_dir / name
            if target.exists():
                target.unlink()
        api_file = api_dir / f"worker{suffix}"
        if api_file.exists():
            api_file.unlink()
        # Legacy flat variant (pre-package layout); newer templates ship
        # the variant inside the load_test package instead.
        load_test_file = services_dir / f"load_test{suffix}"
        if load_test_file.exists():
            load_test_file.unlink()
        lt_service = lt_worker_dir / f"service{suffix}"
        if lt_service.exists():
            lt_service.unlink()

    # Helper: rename backend-specific files to canonical names
    def _rename_backend_files(suffix: str) -> set[str]:
        """Rename *_<backend>.py files to *.py, return set of final names."""
        final_names = {"__init__.py"}

        # Rename queue files
        if queues_dir.exists():
            for backend_file in queues_dir.glob(f"*{suffix}"):
                final_name = backend_file.name.replace(suffix, ".py")
                arq_file = backend_file.with_name(final_name)
                if arq_file.exists():
                    arq_file.unlink()
                backend_file.rename(queues_dir / final_name)
                final_names.add(final_name)

        # Rename worker-dir files (pools, registry, middleware, broker)
        for stem in ["pools", "registry", "middleware", "broker"]:
            backend_file = worker_dir / f"{stem}{suffix}"
            canonical = worker_dir / f"{stem}.py"
            if backend_file.exists():
                if canonical.exists():
                    canonical.unlink()
                backend_file.rename(canonical)

        # Rename API file
        api_backend = api_dir / f"worker{suffix}"
        api_canonical = api_dir / "worker.py"
        if api_backend.exists():
            if api_canonical.exists():
                api_canonical.unlink()
            api_backend.rename(api_canonical)

        # Rename the load_test worker service variant INSIDE the package.
        # (The legacy flat ``load_test_<backend>.py`` rename produced
        # ``app/services/load_test.py``, which the ``load_test/`` package
        # shadowed — non-arq stacks then imported the arq-only service
        # and crashed at startup.)
        lt_service_backend = lt_worker_dir / f"service{suffix}"
        lt_service_canonical = lt_worker_dir / "service.py"
        if lt_service_backend.exists():
            if lt_service_canonical.exists():
                lt_service_canonical.unlink()
            lt_service_backend.rename(lt_service_canonical)

        # Legacy flat variant (pre-package layout) for older trees.
        lt_backend = services_dir / f"load_test{suffix}"
        lt_canonical = services_dir / "load_test.py"
        if lt_backend.exists():
            if lt_canonical.exists():
                lt_canonical.unlink()
            lt_backend.rename(lt_canonical)

        return final_names

    if not queues_dir.exists():
        return

    if worker_backend == WorkerBackends.DRAMATIQ:
        # Using Dramatiq: rename _dramatiq.py files, remove arq + taskiq.
        # Capture whether the template shipped *_dramatiq.py sources
        # this run BEFORE renaming consumes them — this is the signal
        # that distinguishes init (sources present) from update (only
        # canonical files left from a prior init). On update we must
        # NOT run the arq-cleanup glob below, otherwise we'd unlink
        # the canonical system.py / load_test.py we already renamed
        # last time. See issue #672.
        has_dramatiq_sources = any(queues_dir.glob("*_dramatiq.py"))
        dramatiq_final_names = _rename_backend_files("_dramatiq.py")

        if has_dramatiq_sources:
            # Remove arq-only queue files (those without dramatiq
            # counterparts) shipped alongside the just-renamed sources.
            for py_file in queues_dir.glob("*.py"):
                if py_file.name not in dramatiq_final_names:
                    py_file.unlink()

        _remove_backend_files("_taskiq.py")

    elif worker_backend == WorkerBackends.TASKIQ:
        # Using TaskIQ: rename _taskiq.py files, remove arq + dramatiq.
        # See dramatiq branch above for the init-vs-update rationale
        # (issue #672).
        has_taskiq_sources = any(queues_dir.glob("*_taskiq.py"))
        taskiq_final_names = _rename_backend_files("_taskiq.py")

        if has_taskiq_sources:
            for py_file in queues_dir.glob("*.py"):
                if py_file.name not in taskiq_final_names:
                    py_file.unlink()

        _remove_backend_files("_dramatiq.py")

    else:
        # Using arq (default): remove taskiq and dramatiq versions
        _remove_backend_files("_taskiq.py")
        _remove_backend_files("_dramatiq.py")


def cleanup_components(project_path: Path, context: dict[str, Any]) -> None:
    """
    Remove component files based on component selection.

    This function handles component cleanup for both Cookiecutter and Copier
    template engines, ensuring identical behavior.

    Args:
        project_path: Path to the generated project
        context: Dictionary with component/service flags

    Note:
        Handles both Cookiecutter (string "yes"/"no") and Copier (boolean true/false)
        context values for maximum compatibility.
    """

    # Helper to handle both bool and string values from different template engines
    def is_enabled(key: str) -> bool:
        value = context.get(key)
        return value is True or value == "yes"

    # =====================================================================
    # Pattern A: per-spec primary cleanup driven from FileManifest
    # =====================================================================
    # Each non-CORE component and each service declares a `files.primary`
    # list on its spec (see aegis/core/{components,services}.py). When the
    # spec is not selected, we remove every path it owns. Replaces ~150
    # lines of imperative `remove_file` / `remove_dir` calls.
    _cleanable_specs: list[Any] = [
        spec for spec in COMPONENTS.values() if spec.type != ComponentType.CORE
    ]
    _cleanable_specs.extend(SERVICES.values())
    for _spec in _cleanable_specs:
        if not is_enabled(AnswerKeys.include_key(_spec.name)):
            for _rel_path in iter_cleanup_paths(_spec, selected=False):
                apply_cleanup_path(project_path, _rel_path)

    # =====================================================================
    # Pattern B/D: option-driven and backend-variant cleanups (inline).
    # =====================================================================
    # Scheduler service (only useful with persistence; remove on memory backend)
    scheduler_backend = context.get(
        AnswerKeys.SCHEDULER_BACKEND, StorageBackends.MEMORY
    )
    if scheduler_backend == StorageBackends.MEMORY:
        remove_dir(project_path, "app/services/scheduler")
        remove_file(project_path, "app/cli/tasks.py")
        remove_file(project_path, "app/components/backend/api/scheduler.py")
        remove_file(project_path, "tests/api/test_scheduler_endpoints.py")
        remove_file(project_path, "tests/services/test_scheduled_task_manager.py")

    # Worker backend variant (Pattern D). Primary worker cleanup is handled
    # above by the Pattern A loop; this branch only runs when worker IS
    # selected and renames/strips backend-specific suffixes.
    if is_enabled(AnswerKeys.WORKER):
        worker_backend = context.get(AnswerKeys.WORKER_BACKEND, WorkerBackends.ARQ)
        cleanup_worker_backend_files(project_path, worker_backend)

    # Remove shared component integration tests only when BOTH scheduler AND worker disabled
    if not is_enabled(AnswerKeys.SCHEDULER) and not is_enabled(AnswerKeys.WORKER):
        remove_file(project_path, "tests/services/test_component_integration.py")
        remove_file(project_path, "tests/services/test_health_logic.py")

    # Note: per-spec primary cleanup for database / redis / ingress /
    # observability / auth / AI / comms / payment / insights is now driven
    # by the Pattern A loop above, sourced from each spec's
    # `files.primary` list. Sub-feature blocks (auth_org, ai_memory,
    # ollama, ai_rag, ai_voice) remain inline below.

    # Remove OAuth (social login) files when not selected. Auth-only
    # projects without OAuth still have ``OAuthProvider`` /
    # ``UserOAuthIdentity`` SQLModels in ``app/models/user.py`` (the
    # tables ship with the auth migration unconditionally), but the
    # routes, middleware, settings, and tests are scoped here.
    if not is_enabled(AnswerKeys.AUTH_OAUTH):
        remove_file(project_path, "app/components/backend/api/auth/oauth.py")
        remove_file(project_path, "app/components/backend/middleware/session.py")
        remove_file(
            project_path,
            "app/components/frontend/controls/auth/oauth_button.py",
        )
        remove_file(project_path, "tests/api/test_oauth_endpoints.py")
        remove_file(project_path, "tests/services/test_oauth_user_service.py")

    # Remove auth org files if org level not selected (but auth is enabled)
    if is_enabled(AnswerKeys.AUTH) and not is_enabled(AnswerKeys.AUTH_ORG):
        remove_file(project_path, "app/models/org.py")
        remove_file(project_path, "app/services/auth/org_service.py")
        remove_file(project_path, "app/services/auth/membership_service.py")
        remove_file(project_path, "app/services/auth/invite_service.py")
        remove_dir(project_path, "app/components/backend/api/orgs")
        remove_file(
            project_path,
            "app/components/frontend/dashboard/modals/auth_orgs_tab.py",
        )
        remove_file(project_path, "tests/services/test_org_integration.py")
        remove_file(project_path, "tests/api/test_org_endpoints.py")

    # (AI primary cleanup handled by the Pattern A loop above.)

    # AI conversation persistence handling
    # When AI backend is memory (or not specified), remove database-related files
    ai_backend = context.get(AnswerKeys.AI_BACKEND, StorageBackends.MEMORY)
    if ai_backend == StorageBackends.MEMORY:
        remove_file(project_path, "app/models/conversation.py")
        # Remove LLM tracking models (only needed with persistence)
        # Keep app/services/ai/models/__init__.py - contains core types (AIProvider, ProviderConfig)
        remove_dir(project_path, "app/services/ai/models/llm")
        # Agent registry models ride the same persistence gate (the memory
        # backend resolves the default agent from code, not DB rows). The
        # tools.py registry itself stays: it is DB-free and the code-config
        # path still resolves tools through it.
        remove_dir(project_path, "app/services/ai/models/agents")
        remove_file(project_path, "tests/services/ai/test_agent_models.py")
        # Per-user memory needs the agent_user_memory table + async DB.
        remove_file(project_path, "app/services/ai/user_memory.py")
        remove_file(project_path, "tests/services/ai/test_user_memory.py")
        # Memory modules are DB rows (the memory_module table).
        remove_file(project_path, "app/services/ai/memory_modules.py")
        remove_file(project_path, "tests/services/ai/test_memory_modules.py")
        # Reference fetchers query the conversation tables (removed above).
        # The fetcher registry itself (fetchers.py) stays: it is DB-free.
        remove_file(project_path, "app/services/ai/builtin_fetchers.py")
        remove_file(project_path, "tests/services/ai/test_builtin_fetchers.py")
        # Module context assembly reads memory_module rows.
        remove_file(project_path, "app/services/ai/module_context.py")
        remove_file(project_path, "tests/services/ai/test_module_context.py")
        # Sentiment scoring reads/writes conversation + sentiment tables.
        remove_file(project_path, "app/services/ai/sentiment.py")
        remove_file(project_path, "app/services/ai/models/sentiment.py")
        remove_file(project_path, "tests/services/ai/test_sentiment.py")
        # Agent registry CLI inspects DB rows.
        remove_file(project_path, "app/cli/agents.py")
        remove_file(project_path, "tests/cli/test_agents_cli.py")
        # Agent registry admin surface (API service + dashboard tab).
        remove_file(project_path, "app/services/ai/agent_registry.py")
        remove_file(
            project_path,
            "app/components/frontend/dashboard/modals/agents_tab.py",
        )
        remove_file(project_path, "tests/services/ai/test_agent_registry.py")
        # KB metadata models are DB-backed; the rag service itself stays
        # (Chroma is file-based and works without a database).
        remove_file(project_path, "app/services/rag/models/knowledge.py")
        remove_file(project_path, "tests/services/rag/test_knowledge_models.py")
        # chat_kit + usage_recording ledger the LLM catalog + conversation
        # tables removed above, so they only work with a persistent backend.
        remove_dir(project_path, "app/services/ai/chat_kit")
        remove_file(project_path, "app/services/ai/usage_recording.py")
        remove_dir(project_path, "tests/services/ai/chat_kit")
        remove_dir(project_path, "app/services/ai/etl")
        remove_dir(project_path, "app/services/ai/fixtures")
        # Remove persistence-related contexts (keep usage_context.py - no DB deps)
        remove_file(project_path, "app/services/ai/llm_catalog_context.py")
        remove_file(project_path, "app/services/ai/llm_service.py")
        remove_file(project_path, "app/services/ai/provider_management.py")
        # Remove persistence-related tests
        remove_dir(project_path, "tests/services/ai/etl")
        remove_file(project_path, "tests/services/ai/test_usage_tracking.py")
        remove_file(project_path, "tests/services/ai/test_llm_catalog_context.py")
        remove_file(project_path, "tests/services/ai/test_llm_service.py")
        remove_file(project_path, "tests/services/ai/test_provider_management.py")
        # Remove LLM CLI and API (catalog management needs database)
        remove_file(project_path, "app/cli/llm.py")
        remove_file(project_path, "tests/cli/test_llm_cli.py")
        remove_dir(project_path, "app/components/backend/api/llm")
        remove_file(project_path, "tests/api/test_llm_endpoints.py")
        # Remove analytics UI (needs database for usage tracking)
        remove_file(
            project_path, "app/components/frontend/dashboard/modals/ai_analytics_tab.py"
        )
        remove_file(
            project_path, "tests/components/frontend/test_ai_analytics_utils.py"
        )

    # NOTE: the LLM catalog / ETL is provider-agnostic — it syncs model data
    # for whatever providers are configured (public, OpenAI, OpenRouter, …),
    # not just Ollama. Its only Ollama touch point is a single import in
    # ``llm_sync_service`` guarded by ``try/except`` (and a runtime
    # ``OllamaClient is None`` skip), so the chain stays importable with
    # Ollama off. The catalog therefore depends only on PERSISTENCE, removed
    # above when ``ai_backend == memory``. It is intentionally NOT gated on
    # ``ollama_mode`` here: choosing a non-Ollama provider must not strip the
    # ``llm`` command or catalog sync.

    # Remove RAG service if not enabled
    if not is_enabled(AnswerKeys.AI_RAG):
        remove_dir(project_path, "app/components/backend/api/rag")
        remove_dir(project_path, "app/services/rag")
        remove_file(project_path, "app/cli/rag.py")
        remove_dir(project_path, "tests/services/rag")
        # Remove RAG-related files within AI service
        remove_file(project_path, "app/services/ai/rag_context.py")
        remove_file(project_path, "app/services/ai/rag_stats_context.py")
        remove_file(project_path, "tests/services/ai/test_rag_stats_context.py")
        remove_file(project_path, "app/components/frontend/dashboard/modals/rag_tab.py")

    # chat_kit is a pydantic-ai chat engine (imports ``pydantic_ai``); it has
    # no langchain path, so strip it (and its ledger helper) on langchain.
    if (
        is_enabled(AnswerKeys.AI)
        and context.get(AnswerKeys.AI_FRAMEWORK) != AIFrameworks.PYDANTIC_AI
    ):
        remove_dir(project_path, "app/services/ai/chat_kit")
        remove_file(project_path, "app/services/ai/usage_recording.py")
        remove_dir(project_path, "tests/services/ai/chat_kit")

    # Remove voice (TTS/STT) if not enabled
    if not is_enabled(AnswerKeys.AI_VOICE):
        remove_dir(project_path, "app/components/backend/api/voice")
        remove_dir(project_path, "app/services/ai/voice")
        remove_dir(project_path, "tests/services/ai/voice")
        remove_file(project_path, "tests/api/test_voice_endpoints.py")
        remove_file(
            project_path,
            "app/components/frontend/dashboard/modals/voice_settings_tab.py",
        )

    # (comms / payment / insights / auth-dashboard primary cleanups handled
    # by the Pattern A loop above.)

    # Remove services_card.py only if NO services are enabled
    # ServicesCard shows all services, so keep if ANY service is enabled
    if (
        not is_enabled(AnswerKeys.AUTH)
        and not is_enabled(AnswerKeys.AI)
        and not is_enabled(AnswerKeys.COMMS)
        and not is_enabled(AnswerKeys.INSIGHTS)
        and not is_enabled(AnswerKeys.PAYMENT)
        and not is_enabled(AnswerKeys.BLOG)
        and not is_enabled(AnswerKeys.FINANCE)
    ):
        remove_file(
            project_path, "app/components/frontend/dashboard/cards/services_card.py"
        )

    # Remove Alembic directory only if NOTHING needs migrations.
    # Alembic is needed when: auth, insights, payment, blog, AI with a
    # non-memory backend, or a Postgres-backed scheduler (its execution
    # history table ships as a schema-qualified migration).
    include_auth = is_enabled(AnswerKeys.AUTH)
    include_ai = is_enabled(AnswerKeys.AI)
    include_insights = is_enabled(AnswerKeys.INSIGHTS)
    include_payment = is_enabled(AnswerKeys.PAYMENT)
    include_blog = is_enabled(AnswerKeys.BLOG)
    include_finance = is_enabled(AnswerKeys.FINANCE)
    ai_backend = context.get(AnswerKeys.AI_BACKEND, StorageBackends.MEMORY)
    ai_needs_migrations = include_ai and ai_backend != StorageBackends.MEMORY
    scheduler_backend = context.get(
        AnswerKeys.SCHEDULER_BACKEND, StorageBackends.MEMORY
    )
    scheduler_needs_migrations = (
        is_enabled(AnswerKeys.SCHEDULER)
        and scheduler_backend == StorageBackends.POSTGRES
    )
    needs_migrations = (
        include_auth
        or ai_needs_migrations
        or include_insights
        or include_payment
        or include_blog
        or include_finance
        or scheduler_needs_migrations
    )

    if not needs_migrations:
        remove_dir(project_path, "alembic")
        # The model-and-migration skill only applies where alembic exists.
        remove_dir(project_path, ".claude/skills/add-model-and-migration")

    # Clean up empty docs/components directory if no components selected
    if (
        not is_enabled(AnswerKeys.SCHEDULER)
        and not is_enabled(AnswerKeys.WORKER)
        and not is_enabled(AnswerKeys.DATABASE)
        and not is_enabled(AnswerKeys.CACHE)
    ):
        remove_dir(project_path, "docs/components")


def _render_jinja_template(src: Path, dst: Path, project_path: Path) -> None:
    """
    Render a Jinja2 template file and write to destination.

    Args:
        src: Path to the .jinja template file
        dst: Path to write the rendered output (without .jinja extension)
        project_path: Path to the project (used to derive template variables)
    """
    from jinja2 import Environment, FileSystemLoader

    # Get project name from project path
    project_slug = project_path.name

    # Set up Jinja2 environment
    env = Environment(
        loader=FileSystemLoader(src.parent),
        keep_trailing_newline=True,
    )

    # Load and render template
    template = env.get_template(src.name)

    # Build context with common variables
    # These match the variables used in copier.yml
    context = {
        "project_slug": project_slug,
        "project_name": project_slug.replace("-", " ").title(),
        # Service flags - assume true since we're copying service files
        **{AnswerKeys.include_key(name): True for name in SERVICES},
        # Component flags - detect from each spec's marker_path
        **{
            AnswerKeys.include_key(spec.name): (
                project_path / spec.marker_path
            ).exists()
            for spec in COMPONENTS.values()
            if spec.marker_path
        },
        # Legacy flag with no registry spec; sniffed inline.
        "include_cache": (project_path / "app/components/cache").exists(),
        # AI-specific settings (defaults)
        "ai_framework": "anthropic",
        "ai_backend": "sqlite",
        "ai_provider_anthropic": True,
        "ai_provider_openai": False,
    }

    rendered = template.render(**context)

    # Write to destination
    dst.write_text(rendered)


def copy_service_files(
    project_path: Path, service_name: str, template_path: Path
) -> None:
    """
    Copy service-specific files from template to project.

    This is needed when services are added post-generation via Copier update.
    Copier can only re-render existing files - it cannot copy new directories
    that were excluded during initial generation.

    Args:
        project_path: Path to the project directory
        service_name: Name of the service ('auth', 'ai', etc.)
        template_path: Path to the Copier template directory

    Note:
        Uses get_component_file_mapping() to know which files belong to each service.
    """
    # Get the file mapping for this service
    file_mapping = get_component_file_mapping()
    if service_name not in file_mapping:
        brand.warn(f"Unknown service '{service_name}' - skipping file copy")
        return

    service_files = file_mapping[service_name]
    brand.accent(f"Copying {service_name} service files from template...")

    # The template is at: aegis-stack/aegis/templates/copier-aegis-project/{{ project_slug }}/
    # We need to find the template content directory
    template_content = template_path / "{{ project_slug }}"
    if not template_content.exists():
        brand.warn(f"Warning: Template content directory not found: {template_content}")
        return

    copied_count = 0
    for rel_path in service_files:
        src = template_content / rel_path
        dst = project_path / rel_path

        # Check for .jinja version if plain file doesn't exist
        jinja_src = template_content / (rel_path + ".jinja")
        is_jinja_template = False
        if not src.exists() and jinja_src.exists():
            src = jinja_src
            is_jinja_template = True

        # Skip if source doesn't exist (might be conditional on other settings)
        if not src.exists():
            continue

        # Skip if destination already exists (don't overwrite existing customizations)
        if dst.exists():
            continue

        # Create parent directory if needed
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Copy file or directory
        if src.is_dir():
            shutil.copytree(src, dst)
            copied_count += 1
        elif is_jinja_template or src.suffix == ".jinja":
            # Render Jinja2 template
            _render_jinja_template(src, dst, project_path)
            copied_count += 1
        else:
            # Copy regular file
            shutil.copy2(src, dst)
            copied_count += 1

    if copied_count > 0:
        brand.success(f"Copied {copied_count} {service_name} service files")
    else:
        typer.echo(
            f"No {service_name} files copied (may already exist or be templates)"
        )


def install_dependencies(project_path: Path, python_version: str | None = None) -> bool:
    """
    Install project dependencies using uv.

    Args:
        project_path: Path to the project directory
        python_version: Python version for project (currently unused in implementation
                        but required for test mocking and future extensibility)

    Returns:
        True if installation succeeded, False otherwise

    Note:
        We pass --python to uv sync when python_version is specified to ensure
        uv uses the correct Python version and respects the requires-python
        constraint in pyproject.toml. This prevents uv from selecting incompatible
        Python versions (e.g., 3.14 when requires-python = ">=3.11,<3.14").

        When python_version is None, uv sync runs without version constraint,
        allowing uv to auto-detect a compatible Python version.
    """
    try:
        typer.echo(t("postgen.deps_installing"))

        # Unset VIRTUAL_ENV to avoid conflicts with parent project's venv
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)

        # Build command with optional --python flag to enforce version constraint.
        # ``--all-extras`` matches ``make install`` so the dev tools (ruff, ty,
        # pytest) are present — the post-gen ``make fix`` formatting step needs
        # ruff, and without it generated projects shipped unformatted.
        cmd = ["uv", "sync", "--all-extras"]
        if python_version:
            cmd.extend(["--python", python_version])

        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=POST_GEN_TIMEOUT_INSTALL,
            env=env,
        )

        if result.returncode == 0:
            typer.echo(t("postgen.deps_success"))
            return True
        else:
            brand.warn(t("postgen.deps_warn_failed"))
            if result.stderr:
                truncated = _truncate_stderr(result.stderr)
                for line in truncated.split("\n"):
                    typer.echo(f"   {line}")
            brand.muted(t("postgen.deps_manual"))
            return False

    except subprocess.TimeoutExpired:
        brand.warn(t("postgen.deps_timeout"))
        return False
    except FileNotFoundError:
        brand.warn(t("postgen.deps_uv_missing"))
        brand.muted(t("postgen.deps_uv_install"))
        return False
    except Exception as e:
        brand.warn(t("postgen.deps_warn_error", error=e))
        brand.muted(t("postgen.deps_manual"))
        return False


def setup_env_file(project_path: Path) -> bool:
    """
    Copy .env.example to .env if .env doesn't exist.

    Args:
        project_path: Path to the project directory

    Returns:
        True if setup succeeded or .env already exists, False on error
    """
    try:
        typer.echo(t("postgen.env_setup"))
        env_example = project_path / ".env.example"
        env_file = project_path / ".env"

        if env_example.exists() and not env_file.exists():
            shutil.copy(env_example, env_file)
            typer.echo(t("postgen.env_created"))
            return True
        elif env_file.exists():
            typer.echo(t("postgen.env_exists"))
            return True
        else:
            brand.warn(t("postgen.env_missing"))
            return False

    except Exception as e:
        brand.warn(t("postgen.env_error", error=e))
        brand.muted(t("postgen.env_manual"))
        return False


def run_migrations(
    project_path: Path,
    include_migrations: bool = False,
    python_version: str | None = None,
) -> bool:
    """
    Run Alembic database migrations if any service requiring migrations is enabled.

    Migrations are needed when:
    - Auth service is enabled
    - AI service is enabled with a persistence backend (not memory)

    Args:
        project_path: Path to the project directory
        include_migrations: Whether any service requiring migrations is enabled
        python_version: Python version to use (e.g., "3.13") for uv run

    Returns:
        True if migrations succeeded or not needed, False on error
    """
    if not include_migrations:
        return True  # No migrations needed

    try:
        typer.echo(t("postgen.db_setup"))

        # Ensure data directory exists
        data_dir = project_path / "data"
        data_dir.mkdir(exist_ok=True)

        # Verify alembic config exists before running migration
        alembic_ini_path = project_path / "alembic" / "alembic.ini"
        if not alembic_ini_path.exists():
            brand.warn(t("postgen.db_alembic_missing", path=alembic_ini_path))
            brand.muted(t("postgen.db_alembic_hint"))
            return False

        # Run alembic migrations using uv run (ensures correct environment)
        # Unset VIRTUAL_ENV to avoid conflicts with parent project's venv
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)

        # Build command with optional --python flag. `--project` pins uv to
        # the generated project regardless of the caller's cwd or parent
        # venv; without it, running `aegis init` from inside aegis-stack
        # picks up aegis-stack's alembic (which has no sqlmodel) instead
        # of the project's.
        cmd = ["uv", "run", "--project", str(project_path)]
        if python_version:
            cmd.extend(["--python", python_version])
        cmd.extend(["alembic", "-c", str(alembic_ini_path), "upgrade", "head"])

        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=POST_GEN_TIMEOUT_MIGRATION,
            env=env,
        )

        if result.returncode == 0:
            typer.echo(t("postgen.db_success"))
            return True
        else:
            brand.warn(t("postgen.db_failed"))
            if result.stderr:
                truncated = _truncate_stderr(result.stderr)
                for line in truncated.split("\n"):
                    typer.echo(f"   {line}")
            brand.muted(t("postgen.db_manual"))
            return False

    except subprocess.TimeoutExpired:
        brand.warn(t("postgen.db_timeout"))
        return False
    except Exception as e:
        brand.warn(t("postgen.db_error", error=e))
        brand.muted(t("postgen.db_manual"))
        return False


def format_code(project_path: Path) -> bool:
    """
    Auto-format generated code using make fix.

    Args:
        project_path: Path to the project directory

    Returns:
        True if formatting succeeded, False otherwise
    """
    try:
        typer.echo(t("postgen.format_start"))

        # Call make fix to auto-format the generated project
        # Unset VIRTUAL_ENV to avoid conflicts with parent project's venv
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)

        # Retried like run_ruff_on_text: under a loaded machine (parallel
        # CI, uv cache-lock contention) the spawn can fail or time out, and
        # skipping here ships an unformatted project — which the add-path
        # shared-file regen then can't reproduce byte-for-byte.
        result = run_resilient(
            ["make", "fix"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=POST_GEN_TIMEOUT_FORMAT,
            env=env,
            retries=5,
            backoff=1.0,
            retry_on_signal_kill=True,
        )

        if result.returncode == 0:
            typer.echo(t("postgen.format_success"))
            return True
        else:
            brand.warn(t("postgen.format_partial"))
            brand.muted(t("postgen.format_manual"))
            return False

    except FileNotFoundError:
        brand.muted(t("postgen.format_hint"))
        return False
    except subprocess.TimeoutExpired:
        brand.warn(t("postgen.format_timeout"))
        return False
    except Exception as e:
        brand.warn(t("postgen.format_error", error=e))
        brand.muted(t("postgen.format_error_manual"))
        return False


class DependencyInstallationError(Exception):
    """Raised when dependency installation fails during project generation."""

    pass


def seed_ai_fixtures(project_path: Path, python_version: str | None = None) -> bool:
    """
    Seed the AI fixtures into the database.

    Runs the generated project's ``load_all_ai_fixtures``: the LLM catalog
    (vendors, models, deployments, pricing) plus the agent registry's
    default ``assistant`` row.

    Args:
        project_path: Path to the project directory
        python_version: Python version to use (e.g., "3.13") for uv run

    Returns:
        True if seeding succeeded, False otherwise
    """
    try:
        typer.echo(t("postgen.llm_seeding"))

        # Run the seeding script using uv run
        # Unset VIRTUAL_ENV to avoid conflicts with parent project's venv
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)

        # Build command with optional --python flag. `--project` pins uv
        # to the generated project regardless of caller cwd / parent venv.
        cmd = ["uv", "run", "--project", str(project_path)]
        if python_version:
            cmd.extend(["--python", python_version])
        cmd.extend(
            [
                "python",
                "-c",
                "from app.core.db import SessionLocal; "
                "from app.services.ai.fixtures import load_all_ai_fixtures; "
                "load_all_ai_fixtures(SessionLocal())",
            ]
        )

        # Call the fixture loading function in the generated project
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=POST_GEN_TIMEOUT_MIGRATION,
            env=env,
        )

        if result.returncode == 0:
            typer.echo(t("postgen.llm_seed_success"))
            return True
        else:
            brand.warn(t("postgen.llm_seed_failed"))
            if result.stderr:
                # Show truncated error output
                truncated = result.stderr[:500]
                for line in truncated.split("\n"):
                    typer.echo(f"   {line}")
            brand.muted(t("postgen.llm_seed_manual"))
            return False

    except subprocess.TimeoutExpired:
        brand.warn(t("postgen.llm_seed_timeout"))
        return False
    except Exception as e:
        brand.warn(t("postgen.llm_seed_error", error=e))
        return False


def sync_llm_catalog(
    project_path: Path, project_slug: str, python_version: str | None = None
) -> bool:
    """
    Sync LLM catalog from OpenRouter and LiteLLM APIs.

    This runs the `<project_slug> llm sync` CLI command in the generated project
    to fetch live model data from public APIs. This provides up-to-date
    model information including pricing, capabilities, and availability.

    Args:
        project_path: Path to the project directory
        project_slug: Project slug name (used for CLI command)
        python_version: Python version to use (e.g., "3.13") for uv run

    Returns:
        True if sync succeeded, False otherwise (non-critical)
    """
    try:
        typer.echo(t("postgen.llm_syncing"))

        # Unset VIRTUAL_ENV to avoid conflicts with parent project's venv
        env = os.environ.copy()
        env.pop("VIRTUAL_ENV", None)

        # Build command: uv run --project PATH [--python X.Y] project-slug llm sync
        # `--project` pins uv to the generated project regardless of caller
        # cwd / parent venv.
        cmd = ["uv", "run", "--project", str(project_path)]
        if python_version:
            cmd.extend(["--python", python_version])
        cmd.extend([project_slug, "llm", "sync"])

        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=POST_GEN_TIMEOUT_LLM_SYNC,
            env=env,
        )

        if result.returncode == 0:
            typer.echo(t("postgen.llm_sync_success"))
            return True
        else:
            brand.warn(t("postgen.llm_sync_failed"))
            if result.stderr:
                truncated = _truncate_stderr(result.stderr)
                for line in truncated.split("\n"):
                    typer.echo(f"   {line}")
            brand.muted(t("postgen.llm_sync_manual", slug=project_slug))
            return False

    except subprocess.TimeoutExpired:
        brand.warn(t("postgen.llm_sync_timeout"))
        brand.muted(f"Run '{project_slug} llm sync' manually to populate the catalog")
        return False
    except Exception as e:
        brand.warn(t("postgen.llm_sync_error", error=e))
        brand.muted(f"Run '{project_slug} llm sync' manually to populate the catalog")
        return False


def run_post_generation_tasks(
    project_path: Path,
    include_migrations: bool = False,
    python_version: str | None = None,
    seed_ai: bool = False,
    skip_llm_sync: bool = False,
    project_slug: str | None = None,
    reporter: "BuildReporter | None" = None,
) -> bool:
    """
    Run all post-generation tasks for a project.

    This is the main entry point called by both Cookiecutter hooks
    and Copier updaters.

    Args:
        project_path: Path to the generated/updated project
        include_migrations: Whether to run Alembic migrations (auth or AI with persistence)
        python_version: Python version to use (e.g., "3.13")
        seed_ai: Whether AI service with persistence backend is enabled
        skip_llm_sync: Whether to skip LLM catalog sync (--skip-llm-sync flag)
        project_slug: Project slug name (used for CLI commands, derived from path if not provided)

    Returns:
        True if all critical tasks succeeded

    Raises:
        DependencyInstallationError: If dependency installation fails.
            This is a hard failure that aborts project generation.

    Note:
        Dependency installation is critical - if it fails, the entire project
        generation fails. Other tasks (env setup, migrations, formatting, sync) are
        non-critical and won't cause hard failures.
    """
    typer.echo()
    brand.accent(t("postgen.setup_start"), bold=True)

    # Task 1: Install dependencies (CRITICAL - fails entire generation if this fails)
    if reporter is not None:
        reporter.step("deps", t("build.step.deps"), "uv sync")
    deps_success = install_dependencies(project_path, python_version)

    if not deps_success:
        typer.echo()
        brand.error(t("postgen.deps_failed"), bold=True)
        typer.echo()
        brand.muted(t("postgen.deps_failed_detail"))
        brand.muted(t("postgen.deps_failed_hint"))
        raise DependencyInstallationError(
            f"Failed to install dependencies for project at {project_path}"
        )

    if reporter is not None:
        reporter.done("deps")

    # Task 2: Setup .env file (non-critical)
    if reporter is not None:
        reporter.step("env", t("build.step.env"))
    setup_env_file(project_path)
    if reporter is not None:
        reporter.done("env")

    # Task 3: Run migrations if needed (non-critical)
    if reporter is not None and include_migrations:
        reporter.step("migrate", t("build.step.migrate"), "alembic upgrade head")
    run_migrations(project_path, include_migrations, python_version)
    if reporter is not None and include_migrations:
        reporter.done("migrate")

    # Task 4: Seed LLM fixtures and optionally sync from APIs (non-critical)
    if seed_ai:
        if reporter is not None:
            reporter.step("llm", t("build.step.llm"))
        # Derive project_slug from path if not provided
        slug = project_slug or project_path.name

        # Always seed static fixtures first as baseline data
        fixtures_loaded = seed_ai_fixtures(project_path, python_version)

        if skip_llm_sync:
            brand.accent(t("postgen.llm_sync_skipped"))
            if fixtures_loaded:
                brand.muted(t("postgen.llm_fixtures_outdated"))
            brand.muted(t("postgen.llm_sync_hint", slug=slug))
        else:
            # Try to sync from live APIs for up-to-date data
            sync_success = sync_llm_catalog(project_path, slug, python_version)
            if not sync_success and fixtures_loaded:
                brand.muted(t("postgen.llm_fixtures_fallback"))
        if reporter is not None:
            reporter.done("llm")

    # Task 5: Format code (non-critical)
    if reporter is not None:
        reporter.step("format", t("build.step.format"), "ruff")
    format_code(project_path)
    if reporter is not None:
        reporter.done("format")

    # Print final status (only reached if deps succeeded)
    typer.echo()
    brand.success(t("postgen.ready"), bold=True)

    # Show project structure map
    typer.echo()
    render_project_map(project_path)

    typer.echo()
    brand.muted(t("postgen.next_steps"), bold=True)
    typer.echo(t("postgen.next_cd", path=project_path))
    typer.echo(t("postgen.next_serve"))
    typer.echo(t("postgen.next_dashboard"))

    return True
