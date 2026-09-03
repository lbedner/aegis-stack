"""
Component registry and specifications for Aegis Stack.

This module defines all available components, their dependencies, and metadata
used for project generation and validation.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..constants import AnswerKeys, StorageBackends, WorkerBackends
from .file_manifest import FileManifest
from .migration_generator import SCHEDULER_MIGRATION
from .plugins.spec import PluginKind, PluginSpec


def _worker_backend_post_render(project_path: Path, answers: dict[str, Any]) -> None:
    """Resolve worker backend variant files to their canonical names.

    Adapter between the generic ``PluginSpec.post_render`` signature and
    ``post_gen_tasks.cleanup_worker_backend_files``, which holds the real
    rename/strip logic and is shared with the init path. Imported lazily:
    ``post_gen_tasks`` imports from this module, so a top-level import
    would close a cycle.
    """
    from .post_gen_tasks import cleanup_worker_backend_files

    cleanup_worker_backend_files(
        project_path,
        str(answers.get(AnswerKeys.WORKER_BACKEND, WorkerBackends.ARQ)),
    )


class ComponentType(Enum):
    """Component type classifications.

    Anything non-CORE is optional: prompted by the interactive flows,
    addable/removable via ``aegis add``/``aegis remove``. Consumers that
    mean "optional" must filter on ``!= CORE``, never on one specific
    optional type.
    """

    CORE = "core"  # Always included (backend, frontend)
    INFRASTRUCTURE = "infra"  # Redis, workers - foundation for services to use
    FRONTEND = "frontend"  # Optional UI layers (htmx web frontend)


class SchedulerBackend(str, Enum):
    """Scheduler backend options for task persistence."""

    MEMORY = "memory"  # In-memory (no persistence, default)
    SQLITE = "sqlite"  # SQLite database (requires database component)
    POSTGRES = "postgres"  # PostgreSQL (requires a postgres database)


# Core components that are always included in every project
CORE_COMPONENTS = ["backend", "frontend"]


@dataclass(kw_only=True)
class ComponentSpec(PluginSpec):
    """Component-flavoured PluginSpec — back-compat alias for pre-R2 callers.

    Subclasses ``PluginSpec`` and pins ``kind`` to ``COMPONENT`` by default.
    Legacy field names ``requires`` / ``recommends`` continue to work for
    *read* access via the property aliases on ``PluginSpec``; constructions
    in this file use the canonical ``required_components`` /
    ``recommended_components`` names. R2 of the plugin system refactor.

    ``kw_only=True`` is required: ``PluginSpec`` has a required ``kind`` field
    followed by defaulted fields, and overriding ``kind`` with a default in
    this subclass would otherwise violate the "required field after default"
    dataclass rule. Pre-R2 callers all used keyword construction (verified
    by AST scan), so no real call sites are affected.
    """

    kind: PluginKind = PluginKind.COMPONENT


# Component registry - single source of truth
COMPONENTS: dict[str, ComponentSpec] = {
    "backend": ComponentSpec(
        name="backend",
        docs_path="components/backend",
        type=ComponentType.CORE,
        description="FastAPI backend server",
        long_description=(
            "A FastAPI application serving your API, async from the ground "
            "up: typed routes, automatic OpenAPI docs, health checks, and a "
            "test suite already covering all of it."
        ),
        pyproject_deps=["fastapi==0.116.1", "uvicorn==0.35.0"],
        template_files=["app/components/backend/"],
        # backend is a CORE component; never cleaned up.
    ),
    "frontend": ComponentSpec(
        name="frontend",
        docs_path="components/frontend",
        type=ComponentType.CORE,
        description="Flet frontend interface",
        long_description=(
            "A Flet dashboard showing live system health and the status of "
            "every component you pick here, ready to grow into your own "
            "views. Python end to end, no JavaScript build chain."
        ),
        pyproject_deps=["flet==0.28.3"],
        template_files=["app/components/frontend/"],
        # frontend is a CORE component; never cleaned up.
    ),
    "worker": ComponentSpec(
        name="worker",
        docs_path="components/worker",
        type=ComponentType.INFRASTRUCTURE,
        description="Background task processing (arq, Dramatiq, or TaskIQ)",
        long_description=(
            "Background task processing with your choice of backend: arq "
            "(the default), Dramatiq, or TaskIQ. Offload slow work like "
            "emails, exports, and third-party API calls so requests stay "
            "fast. Runs on Redis, which is added automatically."
        ),
        required_components=["redis"],  # Hard dependency
        pyproject_deps=["arq==0.25.0"],
        docker_services=["worker-system", "worker-load-test"],
        template_files=["app/components/worker/"],
        marker_path="app/components/worker",
        files=FileManifest(
            # Mirrors cleanup_components() lines 316-333 (worker NOT enabled).
            # task_history_section.py is intentionally NOT here — cleanup
            # leaves it. worker_taskiq.py IS here — cleanup removes it.
            primary=[
                "app/components/worker",
                ".claude/skills/add-background-job",
                "app/cli/load_test.py",
                # The worker subpackage of the load_test service, including
                # the ``service_<backend>.py`` variants Pattern D resolves
                # to ``service.py`` at generation. The api/ and common/
                # subpackages stay — they back the API load tests.
                "app/services/load_test/worker",
                # Legacy flat service (pre-package layout); only exists in
                # projects generated by older templates.
                "app/services/load_test.py",
                "app/services/load_test_models.py",
                "app/services/load_test_workloads.py",
                "tests/services/test_load_test_models.py",
                "tests/services/test_load_test_service.py",
                "tests/services/test_worker_health_registration.py",
                "tests/services/test_queue_status.py",
                "app/services/system/health_worker.py",
                "app/services/system/health_worker_taskiq.py",
                "app/services/system/health_worker_dramatiq.py",
                "app/services/system/health_worker_rules.py",
                "app/components/backend/api/worker.py",
                "app/components/backend/api/worker_taskiq.py",
                # Entirely-gated stubs (templates wrapped in
                # ``{% if include_worker %}``). Without these here the
                # files render as 0-byte stubs at init and confuse a
                # later ``aegis add-component worker`` — see #686.
                "app/components/backend/api/worker_dramatiq.py",
                "app/components/backend/api/events.py",
                "tests/components/test_worker_events.py",
                "tests/api/test_worker_endpoints.py",
                "app/components/frontend/dashboard/cards/worker_card.py",
                "app/components/frontend/dashboard/modals/worker_modal.py",
                # Worker-only modal section (imported solely by worker_modal);
                # part of the worker footprint so add/remove cover it.
                "app/components/frontend/dashboard/modals/task_history_section.py",
            ],
        ),
        # Pattern D: the templates ship every backend's implementation side
        # by side (``pools_arq.py`` / ``pools_dramatiq.py`` /
        # ``pools_taskiq.py``); choosing one means renaming it onto the
        # canonical name and deleting the rest. A rename is not expressible
        # as a file list or a render diff, so it rides the post_render
        # escape hatch — see PluginSpec.post_render (aegis-stack#921).
        post_render=_worker_backend_post_render,
    ),
    "scheduler": ComponentSpec(
        name="scheduler",
        docs_path="components/scheduler",
        type=ComponentType.INFRASTRUCTURE,
        description="Scheduled task execution infrastructure",
        long_description=(
            "Background task scheduling and cron jobs using APScheduler. "
            "Run periodic work like cleanups, reports, and health checks "
            "on a schedule. Optional database persistence keeps job "
            "history and survives restarts."
        ),
        pyproject_deps=["apscheduler==3.10.4"],
        docker_services=["scheduler"],
        template_files=["app/components/scheduler.py", "app/entrypoints/scheduler.py"],
        marker_path="app/components/scheduler",
        # job_execution history table (Postgres ``scheduler`` schema). Only
        # generated when scheduler_backend != memory — see
        # get_services_needing_migrations().
        migrations=[SCHEDULER_MIGRATION],
        # Backend choice is meaningless without the scheduler; revert it on
        # removal so a later re-add starts from the default rather than
        # inheriting a stale postgres/sqlite selection (aegis-stack#921).
        reset_answers_on_remove={
            AnswerKeys.SCHEDULER_BACKEND: StorageBackends.MEMORY,
            AnswerKeys.SCHEDULER_WITH_PERSISTENCE: False,
        },
        files=FileManifest(
            primary=[
                "app/entrypoints/scheduler.py",
                "app/components/scheduler",
                ".claude/skills/add-scheduled-job",
                "app/services/scheduler/execution_log.py",
                "tests/components/test_scheduler.py",
                "tests/services/test_scheduler_execution_log.py",
                "tests/services/test_scheduler_executions_read.py",
                "docs/components/scheduler.md",
                "app/components/backend/api/scheduler.py",
                "tests/api/test_scheduler_endpoints.py",
                "app/components/frontend/dashboard/cards/scheduler_card.py",
                "app/components/frontend/dashboard/modals/scheduler_modal.py",
                "app/components/frontend/dashboard/modals/scheduler_history_section.py",
                "tests/services/test_scheduled_task_manager.py",
            ],
            # Persistence files render empty when scheduler_backend == memory,
            # so they are kept out of the always-on `primary` add base and
            # added only for the sqlite backend (see get_component_files).
            # They are part of the full footprint, so `aegis remove scheduler`
            # deletes them. Init-time memory-backend cleanup stays inline in
            # cleanup_components() (gated on scheduler_backend, not a toggle).
            extras={
                # Every file gated by ``scheduler_backend != "memory"``.
                # Excluded from the memory add base (they would render empty),
                # added for the sqlite backend, and always part of the full
                # remove footprint. ``app/services/scheduler`` covers
                # ``execution_log.py`` (also memory-gated) via dir expansion.
                "scheduler_persistence": [
                    "app/services/scheduler",
                    "app/cli/tasks.py",
                    "app/components/backend/api/scheduler.py",
                    "tests/api/test_scheduler_endpoints.py",
                    "tests/services/test_scheduled_task_manager.py",
                    "tests/services/test_scheduler_execution_log.py",
                    "tests/services/test_scheduler_executions_read.py",
                ],
            },
        ),
    ),
    "database": ComponentSpec(
        name="database",
        docs_path="components/database",
        type=ComponentType.INFRASTRUCTURE,
        description="Database with SQLModel ORM (SQLite or PostgreSQL)",
        long_description=(
            "Persistent storage with the SQLModel ORM, Alembic migrations, "
            "and connection pooling. SQLite gives you a zero-config file "
            "database for development; PostgreSQL is the production path. "
            "Most services build on this."
        ),
        pyproject_deps=["sqlmodel>=0.0.14", "sqlalchemy>=2.0.0"],
        # Note: async driver (aiosqlite or asyncpg) selected based on database_type in copier.yml
        template_files=["app/core/db.py"],
        marker_path="app/core/db.py",
        files=FileManifest(
            primary=[
                "app/core/db.py",
                "app/components/frontend/dashboard/cards/database_card.py",
                "app/components/frontend/dashboard/modals/database_modal.py",
            ],
        ),
    ),
    "redis": ComponentSpec(
        name="redis",
        type=ComponentType.INFRASTRUCTURE,
        description="Redis cache and message broker",
        long_description=(
            "In-memory data store used as a cache and message broker. "
            "Powers background job queues and pub/sub messaging between "
            "your services, and gives request handlers a fast shared cache."
        ),
        docker_services=["redis"],
        pyproject_deps=["redis==5.0.8"],
        # Redis ships no app/components/redis directory (it's docker config +
        # dashboard widgets), so its always-generated card is the marker.
        marker_path="app/components/frontend/dashboard/cards/redis_card.py",
        files=FileManifest(
            primary=[
                "app/components/frontend/dashboard/cards/redis_card.py",
                "app/components/frontend/dashboard/modals/redis_modal.py",
            ],
        ),
    ),
    "storage": ComponentSpec(
        name="storage",
        docs_path="components/storage",
        type=ComponentType.INFRASTRUCTURE,
        description="S3 object storage, SeaweedFS in dev",
        long_description=(
            "An S3 backend for the object store every stack already has: "
            "documents, chat attachments, anything addressed by its content "
            "hash. Talks to any S3-compatible endpoint; the dev stack ships "
            "SeaweedFS in a container. Switching from the filesystem is a "
            "byte copy, never a migration."
        ),
        docker_services=["seaweedfs"],
        pyproject_deps=["boto3>=1.35"],
        marker_path="app/components/storage",
        files=FileManifest(
            primary=[
                "app/components/storage",
                "app/components/frontend/dashboard/cards/storage_card.py",
                "app/components/frontend/dashboard/modals/storage_modal.py",
                "tests/components/test_storage_s3.py",
            ],
        ),
    ),
    "ingress": ComponentSpec(
        name="ingress",
        docs_path="components/ingress",
        type=ComponentType.INFRASTRUCTURE,
        description="Traefik reverse proxy and load balancer",
        long_description=(
            "Reverse proxy and traffic routing with Traefik: automatic "
            "service discovery, admin endpoint protection, and optional "
            "TLS via Let's Encrypt. The front door for deployments."
        ),
        docker_services=["traefik"],
        recommended_components=["backend"],
        marker_path="traefik",
        files=FileManifest(
            primary=[
                "traefik",
                "app/components/frontend/dashboard/cards/ingress_card.py",
                "app/components/frontend/dashboard/modals/ingress_modal.py",
            ],
        ),
    ),
    "observability": ComponentSpec(
        name="observability",
        docs_path="components/observability",
        type=ComponentType.INFRASTRUCTURE,
        description="Logfire observability, tracing, and metrics",
        long_description=(
            "Distributed tracing, metrics, and log correlation with "
            "Pydantic Logfire. Auto-instruments your application and "
            "adapts to whichever components you enable, so you can see "
            "what production is actually doing."
        ),
        pyproject_deps=["logfire[fastapi,httpx]"],
        template_files=["app/components/backend/middleware/logfire_tracing.py"],
        marker_path="app/components/backend/middleware/logfire_tracing.py",
        files=FileManifest(
            primary=[
                "app/components/backend/middleware/logfire_tracing.py",
                "app/components/frontend/dashboard/cards/observability_card.py",
                "app/components/frontend/dashboard/modals/observability_modal.py",
            ],
        ),
    ),
    "htmx": ComponentSpec(
        name="htmx",
        docs_path="components/web-frontend",
        type=ComponentType.FRONTEND,
        description="Server-rendered htmx web frontend",
        long_description=(
            "Server-rendered pages with Jinja2, htmx, and Alpine.js, styled "
            "with Tailwind and DaisyUI, served at / by the existing "
            "webserver alongside the Flet dashboard at /dashboard. Ships a "
            "generic landing page ready to grow into your own pages."
        ),
        pyproject_deps=["jinja2>=3.1.0"],
        # The htmx tree renders under app/components/web_frontend; the
        # directory is the on-disk marker. Docker watcher services and
        # docs_path land with the asset pipeline and the docs page.
        marker_path="app/components/web_frontend",
        files=FileManifest(
            # The whole tree, its test module, and the node-side build
            # files. Nothing else: app/components/frontend is the CORE Flet
            # frontend and is never gated.
            primary=[
                "app/components/web_frontend",
                "tests/components/test_web_frontend.py",
                # The Tailwind/DaisyUI pipeline. Non-.jinja assets can't be
                # body-gated, so post-gen cleanup is what keeps them out of
                # projects without the htmx frontend.
                "package.json",
                "tailwind.config.js",
            ],
        ),
    ),
}


def get_component(name: str) -> ComponentSpec:
    """Get component specification by name."""
    if name not in COMPONENTS:
        raise ValueError(f"Unknown component: {name}")
    return COMPONENTS[name]


def get_components_by_type(component_type: ComponentType) -> dict[str, ComponentSpec]:
    """Get all components of a specific type."""
    return {
        name: spec for name, spec in COMPONENTS.items() if spec.type == component_type
    }


def list_available_components() -> list[str]:
    """Get list of all available component names."""
    return list(COMPONENTS.keys())
