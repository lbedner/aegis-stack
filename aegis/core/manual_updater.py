"""
Manual project update mechanism (Copier-lite).

This module provides manual component addition/removal without relying on
Copier's git-dependent update mechanism. It directly renders Jinja2 templates
and copies files to the target project.
"""

import re
import shutil
import subprocess
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from jinja2 import TemplateNotFound
from pydantic import BaseModel, Field

from aegis.constants import (
    AnswerKeys,
    AuthLevels,
    ComponentNames,
    StorageBackends,
)
from aegis.i18n import t

from ..cli import brand
from .component_files import (
    JINJA_EXTENSION,
    MIGRATION_SKILL_FILE,
    OWNED_BUT_SHARED_PATHS,
    PROJECT_SLUG_PLACEHOLDER,
    SERVICES_CARD_FILE,
    get_component_cleanup_paths,
    get_component_files,
    get_copier_defaults,
    get_shared_scope,
    get_template_path,
)
from .copier_manager import is_copier_project, load_copier_answers
from .plugins.template_resolver import get_plugin_template_root
from .render_diff import FilePolicy, RenderDiffEngine, build_template_env
from .template_cleanup import run_ruff_on_text
from .verbosity import verbose_print

if TYPE_CHECKING:  # import cycle at runtime; see _spec_for
    from .plugins.spec import PluginSpec

# Constants
COPIER_ANSWERS_HEADER = (
    "# Changes here will be overwritten by Copier; NEVER EDIT MANUALLY\n"
)

# Where a plugin upgrade snapshots files it is about to replace.
# ``.aegis/`` is local-only scratch, already gitignored in generated
# projects alongside ``deploy.yml`` / ``email-setup.json``.
PLUGIN_BACKUP_DIR = Path(".aegis") / "plugin-backups"
DEFAULT_PLUGIN_BACKUP_LABEL = "previous"
# Characters allowed in a backup-directory path segment. Anything else is
# replaced, so a value that reaches the filesystem can never escape
# PLUGIN_BACKUP_DIR via ``/`` or ``..``.
_UNSAFE_PATH_SEGMENT_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _safe_path_segment(value: str) -> str:
    """Reduce ``value`` to something safe to use as one path segment.

    ``spec.name`` and the recorded plugin version both reach the
    filesystem as ``.aegis/plugin-backups/<name>/<version>/``, and neither
    is validated on the install path — ``validate_plugin_name`` only guards
    ``aegis plugins create``, so a pip-installed plugin's ``spec.name`` is
    whatever its ``get_spec()`` returned, and the version is read back from
    the user-editable ``.copier-answers.yml``. A stray ``/`` or ``..`` in
    either would put the snapshot somewhere unintended.

    Not a security boundary — a hostile plugin already executed arbitrary
    code the moment its ``get_spec()`` was called. This is robustness: it
    keeps an odd-but-innocent name or version (``1.0/rc1``) from writing
    outside the backup directory, and it degrades to a readable name
    rather than raising, because losing a *backup location* is not worth
    failing an install over.
    """
    cleaned = _UNSAFE_PATH_SEGMENT_CHARS.sub("_", value).strip(".")
    return cleaned or "unnamed"


# Files with conditional content that should be regenerated when components change.
# These files are not user-editable and contain Jinja conditionals that depend on
# which components/services are enabled.
REGENERATE_ON_COMPONENT_CHANGE = {
    "app/components/backend/api/deps.py",
    "app/components/backend/api/routing.py",
}

# Service flags that gate the cross-spec ``ServicesCard``
# (SERVICES_CARD_FILE, defined next to its engine-scope exclusion in
# ``component_files``). It is shown whenever ANY business service is
# enabled (mirrors the removal in ``post_gen_tasks.cleanup_components``).
# MIGRATION_SKILL_FILE likewise: init removes it alongside ``alembic/``
# when nothing needs migrations, and the first migration-bearing add must
# bring it back (issue #814) via ``ManualUpdater._ensure_migration_skill``.
_SERVICE_ANSWER_KEYS = (
    AnswerKeys.AUTH,
    AnswerKeys.AI,
    AnswerKeys.COMMS,
    AnswerKeys.INSIGHTS,
    AnswerKeys.PAYMENT,
    AnswerKeys.BLOG,
    AnswerKeys.FINANCE,
)


def _is_empty_stub(path: Path) -> bool:
    """Return True if the file at ``path`` has no meaningful Python content.

    Files left behind by a previous init where the owning service's
    templates were gated off render as 0-byte or whitespace-only files.
    ``add_component`` should treat them as fresh rather than preserve
    them as "user files." See issue #686 — Failure A.
    """
    if path.name == "__init__.py":
        return False
    try:
        return not path.read_text().strip()
    except (OSError, UnicodeDecodeError):
        # OSError: races with linting/formatting tools rewriting the file.
        # UnicodeDecodeError: file is binary or non-UTF-8 — treat as
        # non-empty so we never mistake unreadable content for a stub.
        return False


# Directories that should never be swept. Some contain authored content
# that may legitimately be empty (alembic version stubs), some contain
# tooling artefacts (.venv, .git, __pycache__).
_SWEEP_SKIP_DIRS = frozenset(
    {
        ".venv",
        ".git",
        "__pycache__",
        "node_modules",
        "versions",  # alembic/versions
        "__snapshots__",
    }
)


def sweep_empty_stubs(project_path: Path) -> list[str]:
    """Delete 0-byte / whitespace-only ``.py`` files under ``project_path``.

    Whole-file Jinja gates (``{% if include_X %}...{% endif %}``) render
    empty files at init time when the gate is False. Those stubs are
    invisible to per-component manifests, so a later ``add-service``
    won't touch them and the project crashes at import time. This sweep
    is the safety net: any empty ``.py`` that survives generation is
    not authored content, so we delete it. See issue #686 — Failure A.

    ``__init__.py`` files are preserved (empty is the *expected* state
    for a package marker). Skips ``.venv``, ``.git``, ``__pycache__``,
    ``node_modules``, ``alembic/versions/`` (one-line stubs are valid
    there), and snapshot directories. Removes any parent directory that
    becomes empty as a result.

    Returns the list of deleted paths, relative to ``project_path``.
    """
    deleted: list[str] = []
    affected_parents: set[Path] = set()

    for path in project_path.rglob("*.py"):
        # Symlinks are not ours to delete — skip.
        if path.is_symlink():
            continue
        if any(
            part in _SWEEP_SKIP_DIRS for part in path.relative_to(project_path).parts
        ):
            continue
        if not _is_empty_stub(path):
            continue
        try:
            path.unlink()
        except OSError:
            continue
        deleted.append(str(path.relative_to(project_path)))
        affected_parents.add(path.parent)

    # Walk parents bottom-up; an emptied dir may empty its own parent.
    for parent in sorted(affected_parents, key=lambda p: len(p.parts), reverse=True):
        current = parent
        while current != project_path and current.exists():
            try:
                if any(current.iterdir()):
                    break
                current.rmdir()
            except OSError:
                break
            current = current.parent

    return deleted


# Files with Jinja conditionals that depend on auth level (basic/rbac/org).
# Must be regenerated when upgrading auth level.
REGENERATE_ON_AUTH_LEVEL_CHANGE = {
    "app/models/user.py",
    "app/models/org.py",
    "app/core/security.py",
    "app/services/auth/auth_service.py",
    "app/services/auth/org_service.py",
    "app/services/auth/membership_service.py",
    "app/services/auth/invite_service.py",
    "app/components/backend/api/auth/router.py",
    "app/components/backend/api/orgs/router.py",
    "app/components/backend/api/orgs/__init__.py",
    "app/components/backend/api/deps.py",
    "app/components/frontend/dashboard/modals/auth_modal.py",
    "app/components/frontend/dashboard/modals/auth_users_tab.py",
    "app/components/frontend/dashboard/modals/auth_orgs_tab.py",
    "tests/services/test_org_integration.py",
    "tests/api/test_org_endpoints.py",
}


class PluginRenderResult(BaseModel):
    """Outcome of rendering one plugin's template tree into a project."""

    written: list[str] = Field(
        default_factory=list, description="Project-relative paths rendered"
    )
    replaced: list[str] = Field(
        default_factory=list,
        description=(
            "Paths whose existing content differed from the incoming render "
            "and was snapshotted to .aegis/plugin-backups/ before being "
            "overwritten. Empty on a first install or a no-op re-render."
        ),
    )


class UpdateResult(BaseModel):
    """Result of a component update operation."""

    component: str = Field(description="Component that was updated")
    files_modified: list[str] = Field(
        default_factory=list, description="Files that were created/modified"
    )
    files_deleted: list[str] = Field(
        default_factory=list, description="Files that were deleted"
    )
    files_skipped: list[str] = Field(
        default_factory=list, description="Files that already existed and were skipped"
    )
    shared_files_updated: list[str] = Field(
        default_factory=list, description="Shared template files that were regenerated"
    )
    shared_files_backed_up: list[str] = Field(
        default_factory=list,
        description="Shared files that were backed up before update",
    )
    shared_files_need_manual_merge: list[str] = Field(
        default_factory=list, description="Shared files that need manual merging"
    )
    success: bool = Field(description="Whether the operation succeeded")
    error_message: str | None = Field(
        default=None, description="Error message if operation failed"
    )


class ManualUpdater:
    """
    Manual project updater that bypasses Copier's update mechanism.

    This class provides component addition/removal by:
    1. Reading current state from .copier-answers.yml
    2. Rendering Jinja2 templates with updated context
    3. Copying rendered files to project
    4. Updating .copier-answers.yml
    5. Running post-generation tasks
    """

    def __init__(self, project_path: Path):
        """
        Initialize updater for a project.

        Args:
            project_path: Path to the Aegis Stack project

        Raises:
            FileNotFoundError: If project is not a Copier-generated project
        """
        if not is_copier_project(project_path):
            raise FileNotFoundError(
                f"Project at {project_path} was not generated with Copier"
            )

        self.project_path = project_path
        self.template_path = get_template_path()

        # Backfill missing answer keys with copier.yml defaults before any
        # rendering. Without this, undefined variables (e.g. ollama_mode missing
        # from older projects) cause Jinja2 conditionals to inject unrelated
        # component code. See: #504
        copier_defaults = get_copier_defaults()
        self.answers = {**copier_defaults, **load_copier_answers(project_path)}

        # Heal answer-file drift before any shared-file regen consumes
        # ``self.answers``. Without this, a project whose
        # ``.copier-answers.yml`` is missing flags for an already-
        # installed service (e.g. ``include_insights``) regenerates
        # ``app/core/config.py`` with the wrong shape and drops env-
        # bound Settings fields. See issue #686 — Failure B.
        #
        # Only fill keys that are absent from the *persisted* answers
        # file. An explicit ``include_database: false`` written by
        # Copier must not be flipped to True just because the project
        # happens to have an ``alembic/`` dir hanging around — that
        # would over-promote and break the normal add-component path.
        persisted_keys = set(load_copier_answers(project_path).keys())
        reconciled = {
            k: v
            for k, v in self.reconcile_answers_from_disk().items()
            if k not in persisted_keys
        }
        if reconciled:
            self.answers = {**self.answers, **reconciled}
            self._save_answers(self.answers)

        # Template files are at: template/{{ project_slug }}/... — the env
        # is rooted at the template root. Semantics (trim/lstrip/trailing
        # newline) are centralized in build_template_env.
        self.jinja_env = build_template_env(self.template_path)

    @cached_property
    def _render_diff_engine(self) -> RenderDiffEngine:
        """The answers-diff render engine (aegis-stack#916), reusing this
        updater's own Jinja environment so rendering semantics never
        drift between the two."""
        return RenderDiffEngine(
            jinja_env=self.jinja_env,
            template_root=self.template_path,
            project_path=self.project_path,
        )

    @cached_property
    def _shared_scope(self) -> list[str]:
        """Candidate template paths ``_regenerate_shared_files`` may touch:
        every path no component/service manifest claims, plus the one
        documented exception (``get_shared_scope``, aegis-stack#918).
        Cached — neither the template tree nor the component/service
        registry changes within one ``ManualUpdater``'s lifetime.

        This is a *candidate* set, not the final per-call scope: paths in
        ``OWNED_BUT_SHARED_PATHS`` (existence is manifest-owned; only their
        content is cross-cutting) must additionally exist on disk before
        a call may touch them — see ``_regenerate_shared_files``. Without
        that extra check, a project without scheduler would have
        ``scheduler/main.py`` backfill-created by an unrelated operation
        (e.g. adding insights), reproducing the exact bug the old
        ``_REGEN_EXISTING`` "no-create" policy existed to prevent.
        """
        return get_shared_scope(self._render_diff_engine.discover_paths())

    def add_component(
        self,
        component: str,
        additional_data: dict[str, Any] | None = None,
        *,
        run_post_gen: bool = True,
    ) -> UpdateResult:
        """
        Add a component to the project.

        Args:
            component: Component name (e.g., "scheduler", "worker")
            additional_data: Additional configuration data (e.g., scheduler_backend)
            run_post_gen: When False, skip the trailing ``uv sync`` + ``make fix``
                pass. Used by orchestrators (the plugin resolver flow) that batch
                multiple installs and want to amortise post-gen across the whole
                operation by calling :meth:`run_post_generation_tasks` once at
                the end.

        Returns:
            UpdateResult with files modified/skipped

        Raises:
            ValueError: If component is already enabled or no files found
        """
        files_modified: list[str] = []
        files_skipped: list[str] = []
        shared_files_updated: list[str] = []
        shared_files_backed_up: list[str] = []
        shared_files_need_manual_merge: list[str] = []

        try:
            # Check if already enabled
            include_key = AnswerKeys.include_key(component)
            if self.answers.get(include_key) is True:
                # Allow auth level upgrades (basic → rbac → org)
                is_auth_upgrade = (
                    component == AnswerKeys.SERVICE_AUTH
                    and additional_data
                    and AnswerKeys.AUTH_LEVEL in additional_data
                )
                if not is_auth_upgrade:
                    raise ValueError(f"Component '{component}' is already enabled")

            # Merge additional data
            update_data = additional_data or {}
            update_data[include_key] = True

            # Update answers with new component
            updated_answers = {**self.answers, **update_data}

            # Get files for this component
            backend_variant = (
                update_data.get(AnswerKeys.SCHEDULER_BACKEND)
                if component == ComponentNames.SCHEDULER
                else None
            )
            # Pass the post-add answers so option-gated extras (auth org
            # files, htmx auth pages, ai rag/voice) are copied exactly when
            # this project's configuration enables them (issue #814).
            component_files = get_component_files(
                component, backend_variant, answers=updated_answers
            )

            # Some components (like Redis) have no template files - they only
            # configure Docker services and dependencies via shared files
            rendered_files: dict[Path, str] = {}

            if not component_files:
                verbose_print(
                    f"   Component '{component}' has no template files "
                    f"(configured via shared files only)"
                )
                # Continue to regenerate shared files even if no component files
            else:
                # Render and copy each file for this component
                brand.accent(
                    f"   {t('updater.processing_files', count=len(component_files))}"
                )
                for file_path in component_files:
                    # Convert relative path to template path
                    # copier_files: "app/components/scheduler"
                    # template_file: "{{ project_slug }}/app/components/scheduler.jinja"
                    template_file = f"{PROJECT_SLUG_PLACEHOLDER}/{file_path}"

                    # Try with .jinja extension first, then without
                    content = self._render_template_file(template_file, updated_answers)

                    if content is not None:
                        # Output path in project
                        output_path = self.project_path / file_path
                        rendered_files[output_path] = content
                    else:
                        brand.warn(f"   Warning: Template not found for: {file_path}")

                # Copy files to project
                for output_path, content in rendered_files.items():
                    # Create parent directories
                    output_path.parent.mkdir(parents=True, exist_ok=True)

                    relative_path = str(output_path.relative_to(self.project_path))

                    # Check for conflicts
                    if output_path.exists():
                        # Some files have conditional content and must be regenerated
                        is_auth_upgrade = (
                            additional_data
                            and AnswerKeys.AUTH_LEVEL in additional_data
                            and relative_path in REGENERATE_ON_AUTH_LEVEL_CHANGE
                        )
                        # Existing-but-empty files are empty stubs left behind
                        # by an earlier init where this service's templates
                        # were gated off. They're not user content, so
                        # treat them as fresh and write the rendered body.
                        # See issue #686 — Failure A.
                        is_empty_stub = _is_empty_stub(output_path)
                        if (
                            relative_path in REGENERATE_ON_COMPONENT_CHANGE
                            or is_auth_upgrade
                            or is_empty_stub
                        ):
                            self._write_rendered(output_path, content)
                            verbose_print(f"   Regenerated: {relative_path}")
                            files_modified.append(relative_path)
                            continue

                        # For other files, skip existing to preserve user changes
                        verbose_print(f"   Skipping existing file: {relative_path}")
                        files_skipped.append(relative_path)
                        continue

                    # Write file
                    self._write_rendered(output_path, content)
                    verbose_print(f"   Created: {relative_path}")
                    files_modified.append(relative_path)

            # Spec-declared post-render transform, if this component has
            # one (worker's Pattern D backend rename is the only in-tree
            # case). Runs after the component's files are on disk and
            # before shared-file regen, mirroring where init calls it —
            # see PluginSpec.post_render (aegis-stack#921).
            self._run_post_render_hook(component, updated_answers)

            # Regenerate shared template files with updated component configuration
            (
                shared_files_updated,
                shared_files_backed_up,
                shared_files_need_manual_merge,
            ) = self._regenerate_shared_files(updated_answers)

            # Cross-spec: the shared cards/__init__.py just regenerated to
            # import ServicesCard if a service is now present — make sure the
            # module it points at exists (it's removed at init when 0 services).
            created_card = self._ensure_services_card(updated_answers)
            if created_card:
                files_modified.append(created_card)

            # Cross-spec: the first migration-bearing service restores the
            # add-model-and-migration skill that init removed (issue #814).
            created_skill = self._ensure_migration_skill(updated_answers)
            if created_skill:
                files_modified.append(created_skill)

            # Update .copier-answers.yml
            self._save_answers(updated_answers)

            # Sweep any empty .py stubs left by whole-file Jinja gates.
            # Must run AFTER shared-file regen — regen may legitimately
            # turn a previously-empty file into a populated one (e.g.
            # auth's deps.py going from gated-off to gated-on). See
            # issue #686 — Failure A.
            files_deleted = sweep_empty_stubs(self.project_path)

            if run_post_gen:
                self.run_post_generation_tasks()

            return UpdateResult(
                component=component,
                files_modified=files_modified,
                files_skipped=files_skipped,
                files_deleted=files_deleted,
                shared_files_updated=shared_files_updated,
                shared_files_backed_up=shared_files_backed_up,
                shared_files_need_manual_merge=shared_files_need_manual_merge,
                success=True,
            )

        except Exception as e:
            return UpdateResult(
                component=component,
                files_modified=files_modified,
                files_skipped=files_skipped,
                success=False,
                error_message=str(e),
            )

    def add_service(
        self,
        service: str,
        additional_data: dict[str, Any] | None = None,
        *,
        run_post_gen: bool = True,
    ) -> UpdateResult:
        """Install a service: write its files, then run its migrations.

        Services are stored alongside components in the registry, so the
        file-rendering half of the install reuses :meth:`add_component`.
        What's different is the **migration tail**: services that ship
        a ``MIGRATION_SPECS`` entry (auth, ai-with-sqlite, insights, ...)
        need ``alembic`` bootstrapped, a versioned migration generated,
        and the migration applied. Without this tail the service's
        answer flag is set but its tables don't exist, and the project
        boots into a SQLAlchemy ``OperationalError`` on first request.

        ``add_service_command`` does this manually inline; this method
        gives the resolver flow (``aegis add <plugin>`` resolving
        ``required_services``) the same treatment without re-implementing
        the migration sequence.

        Args:
            service: Service name (e.g., ``"auth"``, ``"insights"``).
            additional_data: Optional config dict (auth level, AI
                backend, etc.). Pass ``None`` for the defaults a
                transitive plugin dep gets.
            run_post_gen: When False, skip the trailing ``uv sync`` +
                ``make fix`` pass — caller will run them once at the
                end of a batched operation.

        Returns the same :class:`UpdateResult` shape as
        :meth:`add_component`. Migration steps are best-effort: if
        bootstrap or generation raises, the result still reports
        success for the file install (the user can re-run migrations
        manually). A failed ``run_migrations`` is logged but doesn't
        fail the install — matching how ``add_service_command`` handles
        the same case.
        """
        # Lazy import — keeps ``ManualUpdater`` from pulling the
        # migration_generator surface (and its alembic deps) at module
        # load time. Only services-with-migrations exercise this path.
        from .migration_generator import (
            MIGRATION_SPECS,
            bootstrap_alembic,
            generate_migration,
            service_has_migration,
        )
        from .post_gen_tasks import run_migrations

        result = self.add_component(service, additional_data, run_post_gen=False)
        if not result.success:
            return result

        if service in MIGRATION_SPECS:
            alembic_dir = self.project_path / "alembic"
            if not alembic_dir.exists():
                bootstrap_alembic(self.project_path, self.jinja_env, self.answers)
            if not service_has_migration(self.project_path, service):
                # Answers carry the project's database engine, which decides
                # whether a spec's Postgres schema survives — SQLite has none.
                generate_migration(self.project_path, service, self.answers)
            # run_migrations failure is non-fatal — match
            # add_service_command's behaviour. The user can ``alembic
            # upgrade head`` manually later.
            run_migrations(self.project_path, include_migrations=True)

        if run_post_gen:
            self.run_post_generation_tasks()
        return result

    def remove_component(self, component: str) -> UpdateResult:
        """
        Remove a component from the project.

        Args:
            component: Component name to remove

        Returns:
            UpdateResult with files deleted

        Raises:
            ValueError: If component is not enabled
        """
        files_deleted: list[str] = []

        try:
            # Check if enabled
            include_key = AnswerKeys.include_key(component)
            if not self.answers.get(include_key):
                raise ValueError(f"Component '{component}' is not enabled")

            # Removal deletes the complete footprint (primary + every gated
            # extra), so option-specific files (auth org, AI rag/voice,
            # scheduler persistence) don't leak behind — which is why no
            # backend variant is consulted here.
            #
            # Paths stay unexpanded so a directory is removed as a directory:
            # expanding it to the files the template ships would strand
            # anything the project grew since (``__pycache__``, built assets)
            # and leave the tree behind.
            component_files = get_component_cleanup_paths(component)

            # Delete each file
            deleted_paths: list[Path] = []

            for file_path in component_files:
                full_path = self.project_path / file_path

                if full_path.exists():
                    relative_path = str(full_path.relative_to(self.project_path))

                    if full_path.is_dir():
                        shutil.rmtree(full_path)
                        verbose_print(f"   Removed directory: {relative_path}")
                    else:
                        full_path.unlink()
                        verbose_print(f"   Removed file: {relative_path}")

                    files_deleted.append(relative_path)
                    deleted_paths.append(full_path)

            # Clean up empty parent directories
            for file_path in deleted_paths:
                parent = file_path.parent
                try:
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
                        relative_parent = str(parent.relative_to(self.project_path))
                        verbose_print(f"   Removed empty directory: {relative_parent}")
                except OSError:
                    # Directory not empty or other error, skip
                    pass

            # Update answers
            updated_answers = {**self.answers, include_key: False}

            # Revert answer keys that only mean something while this
            # component is installed, per its spec declaration.
            updated_answers = self._apply_removal_answer_resets(
                component, updated_answers
            )

            # Regenerate shared files BEFORE persisting the new answers, the
            # same order ``add_component`` uses. ``_save_answers`` also
            # reassigns ``self.answers``, and the render-diff engine renders
            # its BASE (pristine baseline) from that: save first and the
            # baseline becomes the post-removal render, so every file that
            # ought to change looks hand-edited, the merge finds base ==
            # ours, and the file is left wired to the component we just
            # deleted. See #869.
            (
                shared_files_updated,
                shared_files_backed_up,
                shared_files_need_manual_merge,
            ) = self._regenerate_shared_files(updated_answers)

            # Update .copier-answers.yml
            self._save_answers(updated_answers)

            # Run post-generation tasks to clean up dependencies
            self.run_post_generation_tasks()

            return UpdateResult(
                component=component,
                files_deleted=files_deleted,
                shared_files_updated=shared_files_updated,
                shared_files_backed_up=shared_files_backed_up,
                shared_files_need_manual_merge=shared_files_need_manual_merge,
                success=True,
            )

        except Exception as e:
            return UpdateResult(
                component=component,
                files_deleted=files_deleted,
                success=False,
                error_message=str(e),
            )

    def _extract_env_vars(self, content: str) -> dict[str, str]:
        """
        Extract environment variable names and values from .env.example content.

        Args:
            content: Content of .env.example file

        Returns:
            Dictionary mapping variable names to their values (or empty string if commented)
        """
        env_vars: dict[str, str] = {}

        for line in content.split("\n"):
            line = line.strip()

            # Skip blank lines
            if not line:
                continue

            # Handle commented variable definitions FIRST (e.g., "# REDIS_URL=...")
            if line.startswith("# ") and "=" in line:
                var_line = line[2:].strip()  # Remove "# " prefix
                if "=" in var_line:
                    var_name = var_line.split("=")[0].strip()
                    var_value = var_line.split("=", 1)[1].strip()
                    env_vars[var_name] = var_value
                continue

            # Skip other comment-only lines (section headers, descriptions, etc.)
            if line.startswith("#"):
                continue

            # Handle active variable definitions (e.g., "REDIS_URL=...")
            if "=" in line:
                var_name = line.split("=")[0].strip()
                var_value = line.split("=", 1)[1].strip()
                env_vars[var_name] = var_value

        return env_vars

    def _run_ruff(
        self, src: str, check_select: str | None, rel_path: str | None = None
    ) -> str | None:
        """Run ruff over ``src`` and return the result, or None on any failure.

        ``check_select`` controls the ``ruff check --fix`` step that runs
        before ``ruff format``:
          - ``""``  → check with the project's configured rule set (used for
            equality comparison, where matching ``make fix`` exactly matters).
          - a value like ``"I"`` → check with only those rules (used before a
            merge, where we must NOT delete code — isort never removes).
          - ``None`` → skip check entirely, format only.

        The temp file lives in the project so ruff discovers the project's
        ``[tool.ruff]`` config by walking up from the file's location.
        """
        return run_ruff_on_text(src, self.project_path, check_select, rel_path=rel_path)

    def _ruff_normalize(self, src: str, rel_path: str | None = None) -> str | None:
        """Return ``src`` run through the project's full ruff (check --fix + format).

        Used to compare two snippets for *semantic* equality (applying the
        same transformation to both sides cancels formatting-only
        differences that ``make fix`` introduces but a user did not), and by
        :meth:`_write_rendered` to format template renders before writing.
        The destructive rules (unused-import removal) are safe in both
        cases: comparison results stay off disk, and written content is
        always a template default, never user code.
        """
        return self._run_ruff(src, "", rel_path)

    def _write_rendered(self, output_path: Path, content: str) -> None:
        """Write a rendered template file, formatted the way init formats it.

        Init runs the project's ruff (check --fix + format) over every
        generated file; writing a raw render here would leave add/remove
        output drifting from init output by formatting alone — e.g. an
        unused import that init stripped reappearing on every regen.
        Rendered content is the template default, never user code, so the
        destructive fix rules are safe. Falls back to the raw render when
        ruff is unavailable or fails.
        """
        if output_path.suffix == ".py":
            # Normalize under the file's real project-relative path so the
            # project's per-file-ignores stay in force (issue #814: a temp
            # name let ruff strip deps.py's intentional re-exports).
            rel = str(output_path.relative_to(self.project_path))
            formatted = self._ruff_normalize(content, rel_path=rel)
            if formatted is not None:
                content = formatted
        output_path.write_text(content)

    @staticmethod
    def _spec_for(component: str) -> "PluginSpec | None":
        """The registry spec for a component or service name, if known.

        Imported lazily — ``components``/``services`` import from this
        module's neighbours, so a top-level import would close a cycle.
        Returns None for names in neither registry (third-party plugins,
        which carry their spec through the ``add_plugin`` path instead).
        """
        from .components import COMPONENTS
        from .services import SERVICES

        return COMPONENTS.get(component) or SERVICES.get(component)

    def _apply_removal_answer_resets(
        self, component: str, updated_answers: dict[str, Any]
    ) -> dict[str, Any]:
        """Revert ``component``'s spec-declared answer keys on removal.

        See :attr:`PluginSpec.reset_answers_on_remove`. Returns the
        answers dict with the resets applied; a no-op (same content) for
        specs that declare none, which is most of them.
        """
        spec = self._spec_for(component)
        if spec is None or not spec.reset_answers_on_remove:
            return updated_answers
        return {**updated_answers, **spec.reset_answers_on_remove}

    def _run_post_render_hook(
        self, component: str, updated_answers: dict[str, Any]
    ) -> None:
        """Invoke ``component``'s spec-declared post-render transform, if any.

        The add-path half of :attr:`PluginSpec.post_render`; init calls the
        same hooks from ``post_gen_tasks.cleanup_components``, so both
        paths produce identical trees. Unknown component names (and specs
        without a hook — the overwhelming majority) are a silent no-op.
        """
        spec = self._spec_for(component)
        if spec is None or spec.post_render is None:
            return
        verbose_print(f"   Running post-render transform for: {component}")
        spec.post_render(self.project_path, updated_answers)

    def _regenerate_shared_files(
        self, updated_answers: dict[str, Any]
    ) -> tuple[list[str], list[str], list[str]]:
        """
        Regenerate shared template files with updated answers.

        Delegates to the render-diff engine (aegis-stack#916/#917),
        scoped to :attr:`_shared_scope` — every template path no
        component/service manifest claims, plus one documented exception
        (``get_shared_scope``, aegis-stack#918). The engine discovers
        which files this operation must touch by rendering
        ``self.answers`` (before) against ``updated_answers`` (after) and
        diffing, rather than from a hand-maintained file list — see
        ``aegis.core.render_diff`` for the full decision table.

        Args:
            updated_answers: Updated Copier answers with component changes

        Returns:
            Tuple of (updated_files, backed_up_files, need_manual_merge_files)
        """
        print(f"\n{t('updater.updating_shared')}")

        env_path = self.project_path / ".env.example"
        old_env_vars = (
            self._extract_env_vars(env_path.read_text()) if env_path.exists() else {}
        )

        # OWNED_BUT_SHARED_PATHS entries only join THIS call's scope when
        # already on disk — their existence is manifest-owned (only
        # content is cross-cutting), so an operation unrelated to their
        # owning component must never backfill-create them. See
        # ``_shared_scope``'s docstring.
        scope = [
            p
            for p in self._shared_scope
            if p not in OWNED_BUT_SHARED_PATHS or (self.project_path / p).exists()
        ]

        engine = self._render_diff_engine
        plans = engine.plan(self.answers, updated_answers, paths=scope)
        policy_by_path = {p.rel_path: p.policy for p in plans}
        result = engine.apply(plans)

        for rel_path in result.created:
            verbose_print(f"   Created: {rel_path}")
        for rel_path in result.overwritten:
            verbose_print(f"   Updated: {rel_path}")
        for rel_path in result.backed_up:
            verbose_print(f"   Backed up: {rel_path}")
        # Whole-file-gated shared files whose gate just turned off (e.g.
        # docker-compose.prod.yml when ingress is removed). Same verbosity
        # level as remove_component's own "Removed file:" lines.
        for rel_path in result.deleted:
            verbose_print(f"   Removed: {rel_path}")
        for rel_path in result.merged:
            print(f"   {t('updater.shared_merged', file=rel_path)}")
        for rel_path in result.conflicts:
            print(f"   {t('updater.shared_conflict', file=rel_path)}")

        # A USER_OWNED preserve is working as designed — the old
        # INTENTIONALLY_NOT_REGENERATED allowlist never surfaced those
        # files at all, since it wasn't even iterated by this method. Only
        # report a preserve as needing attention when the policy promised
        # regeneration and couldn't safely deliver it (diverged
        # WARN_IF_DIVERGED file, or a DEFAULT-policy merge that couldn't
        # run at all).
        reported_preserved = [
            rel_path
            for rel_path in result.preserved
            if policy_by_path.get(rel_path) is not FilePolicy.USER_OWNED
        ]
        for rel_path in reported_preserved:
            print(f"   {t('updater.shared_preserved', file=rel_path)}")

        # Show environment variable changes for .env.example, if it was
        # actually touched this call.
        if env_path.exists() and (
            ".env.example" in result.created
            or ".env.example" in result.overwritten
            or ".env.example" in result.merged
        ):
            new_env_vars = self._extract_env_vars(env_path.read_text())
            added_vars = {
                k: v for k, v in new_env_vars.items() if k not in old_env_vars
            }
            if added_vars:
                verbose_print("   New environment variables:")
                for var_name, var_value in sorted(added_vars.items()):
                    verbose_print(f"      • {var_name}={var_value}")

        shared_files_updated = result.created + result.overwritten + result.merged
        shared_files_backed_up = result.backed_up
        shared_files_need_manual_merge = result.conflicts + reported_preserved

        return (
            shared_files_updated,
            shared_files_backed_up,
            shared_files_need_manual_merge,
        )

    def _answers_need_migrations(self, answers: dict[str, Any]) -> bool:
        """Mirror of post-gen's ``needs_migrations`` gate (``post_gen_tasks``):
        any table-bearing service, or a postgres-backed scheduler."""
        ai_needs = bool(answers.get(AnswerKeys.AI)) and answers.get(
            AnswerKeys.AI_BACKEND
        ) in (StorageBackends.SQLITE, StorageBackends.POSTGRES)
        scheduler_needs = (
            bool(answers.get(AnswerKeys.SCHEDULER))
            and answers.get(AnswerKeys.SCHEDULER_BACKEND) == StorageBackends.POSTGRES
        )
        return bool(
            answers.get(AnswerKeys.AUTH)
            or ai_needs
            or answers.get(AnswerKeys.INSIGHTS)
            or answers.get(AnswerKeys.PAYMENT)
            or answers.get(AnswerKeys.BLOG)
            or answers.get(AnswerKeys.FINANCE)
            or scheduler_needs
        )

    def _ensure_migration_skill(self, answers: dict[str, Any]) -> str | None:
        """Create the add-model-and-migration skill when migrations arrive.

        Init removes ``.claude/skills/add-model-and-migration`` alongside
        ``alembic/`` when nothing needs migrations, so a project that gains
        its first migration-bearing service via ``aegis add`` must get the
        skill back — the add-side mirror of that inline removal, like
        :meth:`_ensure_services_card` (issue #814).

        Returns the project-relative path if it created the file, else None.
        """
        if not self._answers_need_migrations(answers):
            return None
        output_path = self.project_path / MIGRATION_SKILL_FILE
        if output_path.exists():
            return None
        content = self._render_template_file(
            f"{PROJECT_SLUG_PLACEHOLDER}/{MIGRATION_SKILL_FILE}", answers
        )
        if content is None:
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)
        verbose_print(f"   Created cross-spec file: {MIGRATION_SKILL_FILE}")
        return MIGRATION_SKILL_FILE

    def _ensure_services_card(self, answers: dict[str, Any]) -> str | None:
        """Create ``services_card.py`` when an add brings the first service.

        ``ServicesCard`` is rendered at init and removed by post-gen cleanup
        when zero services are selected. On ``add-service`` the first service
        flips that condition back on, and the shared ``cards/__init__.py``
        regenerates to import ``ServicesCard`` — so the module must exist or the
        frontend import chain breaks (``ModuleNotFoundError`` on boot). The
        removal direction lives in ``post_gen_tasks.cleanup_components``; this is
        its add-side mirror.

        Returns the project-relative path if it created the file, else None.
        """
        if not any(answers.get(key) for key in _SERVICE_ANSWER_KEYS):
            return None
        output_path = self.project_path / SERVICES_CARD_FILE
        if output_path.exists():
            return None
        content = self._render_template_file(
            f"{PROJECT_SLUG_PLACEHOLDER}/{SERVICES_CARD_FILE}", answers
        )
        if content is None:
            return None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_rendered(output_path, content)
        verbose_print(f"   Created cross-spec file: {SERVICES_CARD_FILE}")
        return SERVICES_CARD_FILE

    def _render_template_file(
        self, template_file: str, context: dict[str, Any]
    ) -> str | None:
        """
        Render a Jinja2 template file.

        Args:
            template_file: Template file path (relative to template root)
            context: Jinja2 context variables

        Returns:
            Rendered content, or None if template not found
        """
        # Render .jinja templates through Jinja2.
        try:
            template = self.jinja_env.get_template(f"{template_file}{JINJA_EXTENSION}")
            return template.render(context)
        except TemplateNotFound:
            pass

        # Non-.jinja files are copied verbatim — same contract Copier uses.
        # Rendering them through Jinja2 breaks any source that legitimately
        # contains brace syntax (Python f-string {{...}} escapes, Alpine/HTMX
        # attributes, CSS in inline strings, etc.).
        raw_path = self.template_path / template_file
        if raw_path.is_file():
            return raw_path.read_text()
        return None

    def install_plugin_template_tree(
        self, plugin_module_name: str, *, backup_label: str | None = None
    ) -> list[str]:
        """Render the plugin's template tree into the project.

        Thin wrapper over :meth:`render_plugin_tree` preserving the
        original ``list[str]`` contract; see there for the semantics.
        """
        return self.render_plugin_tree(
            plugin_module_name, backup_label=backup_label
        ).written

    def render_plugin_tree(
        self, plugin_module_name: str, *, backup_label: str | None = None
    ) -> PluginRenderResult:
        """Render the plugin's template tree into the project.

        Plugins ship a ``<package>/templates/{{ project_slug }}/...``
        directory parallel to aegis-stack's own. This method locates
        that tree via :func:`aegis.core.plugins.template_resolver.get_plugin_template_root`,
        renders every ``*.jinja`` file through a fresh Jinja2 environment
        rooted at the plugin's templates dir (so ``include`` / ``extends``
        resolve against the plugin's tree, not aegis-stack's), and writes
        the rendered output at the corresponding relative path under
        ``self.project_path``.

        The render context is the project's current ``self.answers``,
        so plugin templates can branch on the same project state that
        aegis-stack templates do (``include_database``, ``database_engine``,
        etc.).

        **Existing files are overwritten — deliberately.** A plugin's
        files are vendored artifacts owned by that plugin, not scaffolding
        the project takes ownership of; an upgrade re-renders them
        wholesale, the way ``npm update`` replaces a package rather than
        merging your edits into it. Editing them is allowed, but an
        upgrade replaces them. (A true 3-way merge isn't even available
        here: pip has already swapped the plugin package by upgrade time,
        so the previous version's templates — the merge base — no longer
        exist on disk.)

        What it does NOT do is destroy work *silently*. Plugin files land
        in the user's own repo next to their code, where "this is
        vendored" isn't self-evident, so any existing file whose content
        differs from the incoming render is first snapshotted under
        ``.aegis/plugin-backups/<backup_label>/`` (``.aegis/`` is already
        gitignored in generated projects) and reported in
        :attr:`PluginRenderResult.replaced`. Unchanged files are not
        backed up, so a routine no-op re-render leaves no litter.

        ``backup_label`` names the snapshot directory — callers pass the
        version being replaced (e.g. ``"scraper/1.2.0"``). Defaults to
        ``"previous"`` when the caller doesn't know it.

        **Filesystem-only.** Uses ``Path.rglob`` and ``FileSystemLoader``
        on the resolver's returned path, which requires a real on-disk
        directory. Zipped wheels are not supported today — see
        ``aegis.core.plugins.template_resolver`` for the rationale.
        """
        template_root = get_plugin_template_root(plugin_module_name)
        if template_root is None:
            return PluginRenderResult()

        # Plugin templates mirror aegis-stack's: every file is nested
        # under ``{{ project_slug }}/`` so the rendered path is naturally
        # rooted at the project tree.
        project_slug_dir = template_root / PROJECT_SLUG_PLACEHOLDER
        if not project_slug_dir.is_dir():
            return PluginRenderResult()

        plugin_env = build_template_env(template_root)
        backup_root = (
            self.project_path
            / PLUGIN_BACKUP_DIR
            / (backup_label or DEFAULT_PLUGIN_BACKUP_LABEL)
        )

        result = PluginRenderResult()
        for source_file in sorted(project_slug_dir.rglob(f"*{JINJA_EXTENSION}")):
            # Path relative to the project slug dir → relative path
            # inside the target project. Strip the ``.jinja`` suffix
            # since the rendered file shouldn't keep it.
            rel_inside_slug = source_file.relative_to(project_slug_dir)
            out_rel = rel_inside_slug.with_suffix("")
            out_path = self.project_path / out_rel

            # Jinja2 needs the template name relative to the loader's
            # root (template_root, not project_slug_dir) so it can
            # resolve includes against sibling files.
            template_name = str(source_file.relative_to(template_root))
            template = plugin_env.get_template(template_name)
            content = template.render(self.answers)

            if self._snapshot_if_replaced(out_path, content, backup_root):
                result.replaced.append(str(out_rel))

            out_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_rendered(out_path, content)
            result.written.append(str(out_rel))

        return result

    def _snapshot_if_replaced(
        self, out_path: Path, incoming: str, backup_root: Path
    ) -> bool:
        """Copy ``out_path`` into ``backup_root`` if the write replaces it.

        "Replaces" means the file exists and its content differs from
        ``incoming`` — an identical re-render is a no-op worth no backup.
        Returns True when a snapshot was taken.

        Comparison is exact rather than whitespace/ruff-normalized: the
        point is "did the bytes on disk change", not "did the author's
        intent change", and an unreadable (binary/non-UTF-8) file is
        snapshotted rather than skipped, since losing it would be the
        worse failure.
        """
        if not out_path.exists():
            return False
        try:
            if out_path.read_text() == incoming:
                return False
        except (OSError, UnicodeDecodeError):
            pass  # unreadable as text — snapshot it rather than risk loss

        backup_path = backup_root / out_path.relative_to(self.project_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out_path, backup_path)
        return True

    def remove_plugin(self, spec: Any) -> UpdateResult:
        """Uninstall a plugin from the project.

        Mirror of :meth:`add_plugin`:

        1. Drop the plugin's ``_plugins[i]`` entry from answers and
           persist.
        2. Regenerate shared template files so the plugin's wiring no
           longer appears in routes / cards / modals / etc.
        3. Apply :class:`FileManifest` cleanup to remove the plugin's
           own files from the project tree.
        4. Run post-generation tasks (``uv sync`` to drop deps).

        Migrations are intentionally NOT rolled back — matches the
        existing ``aegis remove-service`` behaviour. Database tables
        belonging to the plugin remain in place; users can drop them
        manually via ``alembic downgrade`` if desired.

        Returns an :class:`UpdateResult`. ``success=False`` with a
        clear error message if the plugin isn't currently installed.
        """
        from .file_manifest import apply_cleanup_path, iter_cleanup_paths
        from .plugins.composer import PLUGINS_ANSWER_KEY

        files_deleted: list[str] = []
        try:
            # Normalise legacy entries — pre-Round-8 ``_plugins`` data
            # could be a list of strings (``"plugin>=1.0"``); only
            # dict-shaped entries carry a ``name`` field. Filter to the
            # safe shape before reading / rewriting.
            raw_plugins = self.answers.get(PLUGINS_ANSWER_KEY) or []
            existing_plugins: list[dict[str, Any]] = [
                p for p in raw_plugins if isinstance(p, dict)
            ]
            if not any(p.get("name") == spec.name for p in existing_plugins):
                raise ValueError(
                    f"Plugin {spec.name!r} is not installed in this project"
                )

            updated_plugins = [
                p for p in existing_plugins if p.get("name") != spec.name
            ]
            updated_answers = {**self.answers, PLUGINS_ANSWER_KEY: updated_plugins}

            # Shared file regen — the plugin is no longer in ``_plugins``, so
            # its wiring loops emit nothing for it. This runs BEFORE the
            # answers are persisted: ``_save_answers`` reassigns
            # ``self.answers``, which is what the render-diff engine renders
            # its BASE (pristine baseline) from, so saving first makes every
            # file needing regeneration look hand-edited and it gets skipped.
            # Same bug as remove_component's. See #869.
            (
                shared_updated,
                shared_backed_up,
                shared_manual_merge,
            ) = self._regenerate_shared_files(updated_answers)

            # Persist. If the disk cleanup below fails, the answers still
            # reflect reality and a re-run picks up where we left off.
            self._save_answers(updated_answers)

            # Plugin's own files. ``FileManifest.iter_cleanup_paths``
            # with ``selected=False`` walks the manifest as if the
            # plugin were never selected, yielding everything to
            # delete.
            for rel_path in iter_cleanup_paths(spec, selected=False):
                target = self.project_path / rel_path
                if not target.exists():
                    continue
                apply_cleanup_path(self.project_path, rel_path)
                files_deleted.append(rel_path)

            self.run_post_generation_tasks()

            return UpdateResult(
                component=spec.name,
                files_deleted=files_deleted,
                shared_files_updated=shared_updated,
                shared_files_backed_up=shared_backed_up,
                shared_files_need_manual_merge=shared_manual_merge,
                success=True,
            )
        except Exception as e:
            return UpdateResult(
                component=spec.name,
                files_deleted=files_deleted,
                success=False,
                error_message=str(e),
            )

    def add_plugin(
        self,
        spec: Any,
        plugin_module_name: str,
        plugin_options: dict[str, Any] | None = None,
        *,
        run_post_gen: bool = True,
    ) -> UpdateResult:
        """Install a plugin into the project.

        Higher-level than :meth:`install_plugin_template_tree` —
        this is the full ``aegis add <plugin>`` operation:

        1. Serialise the plugin spec into a ``_plugins[i]`` entry
           (predicates evaluated against the merged opts dict, see
           ``plugin_composer``).
        2. Append it to ``self.answers["_plugins"]`` and persist.
        3. Regenerate shared template files so the new plugin loops
           emit imports / wiring for this plugin.
        4. Drop the plugin's own template tree into the project.
        5. Run post-generation tasks (``uv sync`` + format), unless the
           caller asked to defer them via ``run_post_gen=False``.

        Returns an :class:`UpdateResult` describing the surface area
        that changed. Existing plugin entries with the same name are
        replaced (idempotent).

        ``run_post_gen=False`` is used by the resolver flow in
        ``aegis add`` — it batches multiple component / service /
        plugin installs and runs ``uv sync`` + ``make fix`` exactly
        once at the end (avoids the N+1 sync that nesting would
        otherwise produce).
        """
        from .plugins.composer import PLUGINS_ANSWER_KEY, serialize_plugin_to_answer

        files_modified: list[str] = []
        try:
            # Normalise legacy entries — see ``remove_plugin`` for the
            # full rationale. Same filter; same intent.
            raw_plugins = self.answers.get(PLUGINS_ANSWER_KEY) or []
            existing_plugins: list[dict[str, Any]] = [
                p for p in raw_plugins if isinstance(p, dict)
            ]
            # The version being replaced, captured before the entry is
            # dropped below — names the backup dir for any plugin file
            # this install overwrites.
            previous_entry = next(
                (p for p in existing_plugins if p.get("name") == spec.name), None
            )
            previous_version = (previous_entry or {}).get("version")
            # Idempotent: same plugin name replaces an existing entry
            # rather than duplicating. Plugin authors who want re-add
            # semantics use ``aegis remove`` + ``aegis add`` explicitly.
            existing_plugins = [
                p for p in existing_plugins if p.get("name") != spec.name
            ]

            entry = serialize_plugin_to_answer(
                spec,
                plugin_options=plugin_options,
                project_answers=self.answers,
            )
            existing_plugins.append(entry)

            updated_answers = {**self.answers, PLUGINS_ANSWER_KEY: existing_plugins}

            # Shared file regen BEFORE persisting, the same order
            # ``remove_plugin`` and ``remove_component`` use. Regen renders
            # its BASE from ``self.answers`` and its OURS from
            # ``updated_answers``; ``_save_answers`` rebinds
            # ``self.answers`` to the dict it is handed, so persisting
            # first makes both sides the same object — every file compares
            # equal to itself, nothing is classified as changed, and the
            # plugin's ``{% for p in _plugins %}`` wiring never reaches
            # the project. Same bug class as #869. See
            # ``tests/cli/test_add_plugin_shared_regen.py``.
            (
                shared_updated,
                shared_backed_up,
                shared_manual_merge,
            ) = self._regenerate_shared_files(updated_answers)
            files_modified.extend(shared_updated)

            # Persist once regen has its pre-operation baseline. Still
            # before this method returns, so the resolver flow's next
            # ManualUpdater reads the plugin back from disk.
            self._save_answers(updated_answers)

            # Plugin's own template tree — renders with ``self.answers``,
            # which now includes this plugin. Vendored semantics: existing
            # files are replaced, but anything whose content differed is
            # snapshotted under the version it's replacing and reported.
            backup_label = (
                f"{_safe_path_segment(spec.name)}/"
                f"{_safe_path_segment(str(previous_version))}"
                if previous_version
                else DEFAULT_PLUGIN_BACKUP_LABEL
            )
            plugin_render = self.render_plugin_tree(
                plugin_module_name, backup_label=backup_label
            )
            files_modified.extend(plugin_render.written)
            if plugin_render.replaced:
                brand.warn(
                    t(
                        "plugins.local_changes_replaced",
                        count=len(plugin_render.replaced),
                        name=spec.name,
                        path=f"{PLUGIN_BACKUP_DIR / backup_label}",
                    )
                )

            # Post-gen — uv sync picks up the plugin's pyproject deps,
            # make fix re-formats anything we touched. Skipped when the
            # caller (resolver flow) is batching installs and will run
            # post-gen once at the end.
            if run_post_gen:
                self.run_post_generation_tasks()

            return UpdateResult(
                component=spec.name,
                files_modified=files_modified,
                shared_files_updated=shared_updated,
                shared_files_backed_up=shared_backed_up,
                shared_files_need_manual_merge=shared_manual_merge,
                success=True,
            )
        except Exception as e:
            return UpdateResult(
                component=spec.name,
                files_modified=files_modified,
                success=False,
                error_message=str(e),
            )

    def _save_answers(self, answers: dict[str, Any]) -> None:
        """
        Save updated answers to .copier-answers.yml.

        Args:
            answers: Updated answers dictionary
        """
        import yaml

        answers_file = self.project_path / AnswerKeys.ANSWERS_FILENAME

        # Preserve metadata
        answers_with_meta = {
            **answers,
            "_commit": answers.get("_commit", "None"),
            "_src_path": answers.get("_src_path", str(self.template_path)),
        }

        with open(answers_file, "w") as f:
            f.write(COPIER_ANSWERS_HEADER)
            yaml.safe_dump(
                answers_with_meta, f, default_flow_style=False, sort_keys=False
            )

        self.answers = answers

    def reconcile_answers_from_disk(self) -> dict[str, Any]:
        """Infer ``include_*`` / ``auth_level`` flags from filesystem markers.

        Some legacy projects have a ``.copier-answers.yml`` that is
        missing flags for services that are actually installed on disk
        (we've seen this with ``include_insights`` and its sub-flags).
        When that happens, ``_regenerate_shared_files`` renders shared
        templates with the wrong gating and drops env-bound Settings
        fields, which causes Pydantic ``extra_forbidden`` crashes on
        boot. See issue #686 — Failure B.

        This method walks well-known marker paths and returns a dict
        of flags to set ``True`` (or, for ``auth_level``, the inferred
        level). It only ever **promotes** — never demotes a flag that
        is already ``True`` in answers — because file presence is a
        strong "installed" signal but absence isn't a reliable "not
        installed" signal (a service could have been partially removed
        manually).
        """
        proj = self.project_path
        inferred: dict[str, Any] = {}

        def has_file(*relative: str) -> bool:
            full = proj
            for part in relative:
                full = full / part
            return full.is_file()

        def has_nonstub_dir(*relative: str) -> bool:
            full = proj
            for part in relative:
                full = full / part
            if not full.is_dir():
                return False
            for child in full.rglob("*.py"):
                if child.name == "__init__.py":
                    continue
                try:
                    if child.read_text().strip():
                        return True
                except (OSError, UnicodeDecodeError):
                    continue
            return False

        # Services
        if has_file("app", "services", "auth", "auth_service.py"):
            inferred[AnswerKeys.AUTH] = True
        if has_file("app", "services", "ai", "ai_service.py"):
            inferred[AnswerKeys.AI] = True
        if has_nonstub_dir("app", "services", "insights"):
            inferred[AnswerKeys.INSIGHTS] = True
        if has_nonstub_dir("app", "services", "blog"):
            inferred[AnswerKeys.BLOG] = True
        if has_nonstub_dir("app", "services", "payment"):
            inferred[AnswerKeys.PAYMENT] = True
        if has_nonstub_dir("app", "services", "comms"):
            inferred[AnswerKeys.COMMS] = True

        # Components
        if (proj / "alembic").is_dir() or has_nonstub_dir("app", "models"):
            inferred[AnswerKeys.DATABASE] = True
        if has_nonstub_dir("app", "components", "scheduler"):
            inferred[AnswerKeys.SCHEDULER] = True
        if has_nonstub_dir("app", "components", "worker"):
            inferred[AnswerKeys.WORKER] = True
        if has_nonstub_dir("app", "components", "backend", "observability"):
            inferred[AnswerKeys.OBSERVABILITY] = True
        if has_nonstub_dir("app", "components", "backend", "ingress"):
            inferred[AnswerKeys.INGRESS] = True

        # Auth level — only meaningful if auth itself is installed.
        # RBAC is gated by inline ``{% if include_auth_rbac %}`` blocks
        # in existing files rather than a dedicated module, so we sniff
        # ``def require_role`` in the rendered auth_service.py — that
        # symbol is only emitted when RBAC is on. Org is detected via
        # the org_service.py module (whole-file gated).
        if inferred.get(AnswerKeys.AUTH) or self.answers.get(AnswerKeys.AUTH):
            auth_svc = proj / "app" / "services" / "auth" / "auth_service.py"
            has_require_role = False
            if auth_svc.is_file():
                try:
                    has_require_role = "def require_role" in auth_svc.read_text()
                except (OSError, UnicodeDecodeError):
                    has_require_role = False
            if has_file("app", "services", "auth", "org_service.py"):
                inferred[AnswerKeys.AUTH_LEVEL] = AuthLevels.ORG
                inferred[AnswerKeys.AUTH_ORG] = True
                inferred[AnswerKeys.AUTH_RBAC] = True
            elif has_require_role:
                inferred[AnswerKeys.AUTH_LEVEL] = AuthLevels.RBAC
                inferred[AnswerKeys.AUTH_RBAC] = True

        # Auth OAuth marker — file may exist as a non-stub when oauth was wired
        if has_file("app", "components", "backend", "api", "auth", "oauth.py"):
            oauth_path = (
                proj / "app" / "components" / "backend" / "api" / "auth" / "oauth.py"
            )
            try:
                if oauth_path.read_text().strip():
                    inferred[AnswerKeys.AUTH_OAUTH] = True
            except (OSError, UnicodeDecodeError):
                pass

        # Insights sub-flags
        collectors_dir = proj / "app" / "services" / "insights" / "collectors"
        if collectors_dir.is_dir():
            for source, key in (
                ("github", AnswerKeys.INSIGHTS_GITHUB),
                ("pypi", AnswerKeys.INSIGHTS_PYPI),
                ("plausible", AnswerKeys.INSIGHTS_PLAUSIBLE),
                ("reddit", AnswerKeys.INSIGHTS_REDDIT),
            ):
                if (collectors_dir / f"{source}_collector.py").is_file():
                    inferred[key] = True

        return inferred

    def run_post_generation_tasks(self) -> None:
        """
        Run post-generation tasks (uv sync, make fix).

        Public so callers that batch multiple ``add_*`` operations
        (e.g. the plugin resolver flow in ``aegis add``) can defer
        sync/format with ``run_post_gen=False`` per call and invoke
        this exactly once at the end of the whole operation.

        This ensures:
        - Dependencies are updated
        - Code is auto-formatted
        - Imports are organized
        """
        print(f"\n{t('updater.running_postgen')}")

        # Run uv sync to update dependencies
        try:
            subprocess.run(
                ["uv", "sync", "--all-extras"],
                cwd=self.project_path,
                check=True,
                capture_output=True,
            )
            print(f"   {t('updater.deps_synced')}")
        except subprocess.CalledProcessError as e:
            print(f"   Warning: Failed to sync dependencies: {e}")

        # Run make fix to auto-format code
        try:
            subprocess.run(
                ["make", "fix"],
                cwd=self.project_path,
                check=True,
                capture_output=True,
            )
            print(f"   {t('updater.code_formatted')}")
        except subprocess.CalledProcessError:
            typer.echo(
                "   "
                + brand.warn_text("Warning:")
                + " "
                + brand.accent_text("make fix")
                + " had issues. Run it manually to see details."
            )


def add_component_manual(
    project_path: Path,
    component: str,
    additional_data: dict[str, Any] | None = None,
) -> None:
    """
    Convenience function to add a component to a project.

    Args:
        project_path: Path to the Aegis Stack project
        component: Component name
        additional_data: Additional configuration data
    """
    updater = ManualUpdater(project_path)
    updater.add_component(component, additional_data)


def remove_component_manual(project_path: Path, component: str) -> None:
    """
    Convenience function to remove a component from a project.

    Args:
        project_path: Path to the Aegis Stack project
        component: Component name
    """
    updater = ManualUpdater(project_path)
    updater.remove_component(component)
