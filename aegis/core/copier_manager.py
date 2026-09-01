"""
Copier template engine integration.

This module provides Copier template generation functionality alongside
the existing Cookiecutter engine. It's designed to maintain feature parity
during the migration period.
"""

from pathlib import Path
from typing import Any, Literal

import typer
import yaml
from copier import run_copy, run_update

from aegis import __version__
from aegis.i18n import t

from ..cli import brand
from ..config.defaults import (
    DEFAULT_PYTHON_VERSION,
    GITHUB_TEMPLATE_URL,
    version_to_git_tag,
)
from ..constants import (
    AIFrameworks,
    AIProviders,
    AnswerKeys,
    AuthLevels,
    OllamaMode,
    PaymentProviders,
    PostgresProviders,
    StorageBackends,
    WorkerBackends,
)
from .build_reporter import BuildReporter
from .components import COMPONENTS, ComponentType
from .migration_generator import (
    generate_migrations_for_services,
    get_services_needing_migrations,
)
from .post_gen_tasks import cleanup_components, run_post_generation_tasks
from .services import SERVICES
from .template_generator import TemplateGenerator
from .verbosity import is_verbose, verbose_print


def derive_include_flags(template_context: dict[str, Any]) -> dict[str, bool]:
    """One ``include_<name>`` Copier bool per optional component and service.

    The registries are the source of truth for which include flags exist, so
    a new spec flows into Copier data with no hand-written entry here. The
    context values are the generator's cookiecutter-era "yes"/"no" strings;
    a key absent from the context counts as "no".
    """
    names = [
        name for name, spec in COMPONENTS.items() if spec.type != ComponentType.CORE
    ]
    names.extend(SERVICES)
    return {
        AnswerKeys.include_key(name): template_context.get(
            AnswerKeys.include_key(name), "no"
        )
        == "yes"
        for name in names
    }


def is_git_repo(path: Path) -> bool:
    """
    Check if path is inside a git repository.

    Args:
        path: Path to check

    Returns:
        True if path has a .git directory (is a git repo root)
    """
    return (path / ".git").exists()


def generate_with_copier(
    template_gen: TemplateGenerator,
    output_dir: Path,
    vcs_ref: str | None = None,
    skip_llm_sync: bool = False,
    dev_mode: bool = False,
    reporter: "BuildReporter | None" = None,
) -> Path:
    """
    Generate project using Copier template engine.

    Args:
        template_gen: Template generator with project configuration
        output_dir: Directory to create the project in
        vcs_ref: Git reference (tag, branch, or commit) to generate from
        skip_llm_sync: Whether to skip LLM catalog sync after generation

    Returns:
        Path to the generated project

    Note:
        This function uses the Copier template which is currently incomplete
        (missing conditional _exclude patterns). Projects will include all
        components regardless of selection until template is fixed.
    """
    import shutil
    import subprocess
    import tempfile

    # Get template context from template generator
    template_context = template_gen.get_template_context()

    python_version = template_context.get("python_version", DEFAULT_PYTHON_VERSION)

    # Convert template context to Copier data format
    # Copier uses boolean values instead of "yes"/"no" strings
    copier_data = {
        "project_name": template_context["project_name"],
        "project_slug": template_context["project_slug"],
        "project_description": template_context.get(
            "project_description",
            "A production-ready async Python application built with Aegis Stack",
        ),
        "author_name": template_context.get("author_name", "Your Name"),
        "author_email": template_context.get("author_email", "your.email@example.com"),
        "github_username": template_context.get("github_username", "your-username"),
        "version": template_context.get("version", "0.1.0"),
        "python_version": python_version,  # Uses override for RAG + Python 3.14
        "aegis_version": template_context.get("aegis_version", "0.0.0"),
        # include_<name> bools, one per optional component/service, derived
        # from the plugin registries (yes/no strings -> Copier booleans).
        **derive_include_flags(template_context),
        AnswerKeys.SCHEDULER_BACKEND: template_context[AnswerKeys.SCHEDULER_BACKEND],
        AnswerKeys.SCHEDULER_WITH_PERSISTENCE: template_context[
            AnswerKeys.SCHEDULER_WITH_PERSISTENCE
        ]
        == "yes",
        AnswerKeys.WORKER_BACKEND: template_context.get(
            AnswerKeys.WORKER_BACKEND, WorkerBackends.ARQ
        ),
        AnswerKeys.DATABASE_ENGINE: template_context.get(
            AnswerKeys.DATABASE_ENGINE, StorageBackends.SQLITE
        ),
        AnswerKeys.POSTGRES_PROVIDER: template_context.get(
            AnswerKeys.POSTGRES_PROVIDER, PostgresProviders.CONTAINER
        ),
        AnswerKeys.CACHE: False,  # Default to no
        AnswerKeys.AUTH_LEVEL: template_context.get(
            AnswerKeys.AUTH_LEVEL, AuthLevels.BASIC
        ),
        AnswerKeys.AUTH_RBAC: template_context.get(AnswerKeys.AUTH_RBAC, "no") == "yes",
        AnswerKeys.AUTH_ORG: template_context.get(AnswerKeys.AUTH_ORG, "no") == "yes",
        AnswerKeys.AUTH_OAUTH: template_context.get(AnswerKeys.AUTH_OAUTH, "no")
        == "yes",
        AnswerKeys.AI_FRAMEWORK: template_context.get(
            AnswerKeys.AI_FRAMEWORK, AIFrameworks.PYDANTIC_AI
        ),
        AnswerKeys.AI_PROVIDERS: template_context.get(
            AnswerKeys.AI_PROVIDERS, AIProviders.OPENAI
        ),
        AnswerKeys.AI_BACKEND: template_context.get(
            AnswerKeys.AI_BACKEND, StorageBackends.MEMORY
        ),
        AnswerKeys.AI_WITH_PERSISTENCE: template_context.get(
            AnswerKeys.AI_WITH_PERSISTENCE, "no"
        )
        == "yes",
        AnswerKeys.AI_RAG: template_context.get(AnswerKeys.AI_RAG, "no") == "yes",
        AnswerKeys.AI_VOICE: template_context.get(AnswerKeys.AI_VOICE, "no") == "yes",
        AnswerKeys.OLLAMA_MODE: template_context.get(
            AnswerKeys.OLLAMA_MODE, OllamaMode.NONE
        ),
        AnswerKeys.INSIGHTS_GITHUB: template_context.get(
            AnswerKeys.INSIGHTS_GITHUB, "no"
        )
        == "yes",
        AnswerKeys.INSIGHTS_PYPI: template_context.get(AnswerKeys.INSIGHTS_PYPI, "no")
        == "yes",
        AnswerKeys.INSIGHTS_PLAUSIBLE: template_context.get(
            AnswerKeys.INSIGHTS_PLAUSIBLE, "no"
        )
        == "yes",
        AnswerKeys.INSIGHTS_REDDIT: template_context.get(
            AnswerKeys.INSIGHTS_REDDIT, "no"
        )
        == "yes",
        AnswerKeys.INSIGHTS_PER_USER: template_context.get(
            AnswerKeys.INSIGHTS_PER_USER, "no"
        )
        == "yes",
        AnswerKeys.PAYMENT_PROVIDER: template_context.get(
            AnswerKeys.PAYMENT_PROVIDER, PaymentProviders.DEFAULT
        ),
    }

    # Detect dev vs production mode for template sourcing
    # - Dev mode (--dev flag): Use plain file path to read from working tree
    # - Development: Use git+file:// URL to access local git repo at HEAD
    # - Production (pip/uvx install): Use GitHub URL (no local git repo)
    from .copier_updater import get_template_root, resolve_version_to_ref

    template_root = get_template_root()

    dev_template_dir: tempfile.TemporaryDirectory[str] | None = None

    if dev_mode:
        # Dev mode: read directly from working tree (uncommitted changes)
        # WARNING: Projects generated in dev mode cannot be updated with aegis update
        dev_template_dir = tempfile.TemporaryDirectory(prefix="aegis-template-dev-")
        dev_template_root = Path(dev_template_dir.name)
        shutil.copy2(template_root / "copier.yml", dev_template_root / "copier.yml")
        template_subdir = Path("aegis") / "templates" / "copier-aegis-project"
        shutil.copytree(
            template_root / template_subdir,
            dev_template_root / template_subdir,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        template_source = str(dev_template_root)
        resolved_ref = None  # No version pinning in dev mode
    elif is_git_repo(template_root):
        # Development mode: local git repository available
        # Always use git+file:// URL so projects are updatable
        template_source = f"git+file://{template_root}"
        if vcs_ref:
            # Specific version requested - resolve to git reference
            resolved_ref = resolve_version_to_ref(vcs_ref, template_root)
        else:
            # No version specified - use HEAD so project has valid _commit
            # This is CRITICAL for aegis update to work properly
            resolved_ref = "HEAD"
    else:
        # Production mode: installed via pip/uvx (no .git directory)
        # Use GitHub URL for template source with CLI version as default ref
        # This ensures CLI v0.4.1 uses template v0.4.1, not HEAD
        template_source = GITHUB_TEMPLATE_URL
        resolved_ref = vcs_ref if vcs_ref else version_to_git_tag(__version__)

    # Store template version in answers for future reference
    # This allows aegis update to show "v0.4.1" instead of commit hash
    if resolved_ref is None:
        # Dev mode - no version tracking
        copier_data["_template_version"] = "dev"
    elif resolved_ref.startswith("v"):
        # Version tag (e.g., "v0.4.1") -> strip 'v' prefix
        copier_data["_template_version"] = resolved_ref[1:]
    else:
        # Branch or commit hash - store as-is
        copier_data["_template_version"] = resolved_ref

    # Generate project - Copier creates output_dir/project_slug via {{ project_slug }}/ wrapper
    # NOTE: _tasks removed from copier.yml - we run them ourselves below
    # Suppress Copier output unless --verbose flag is passed
    if reporter is not None:
        reporter.step("render", t("build.step.render"))
    try:
        run_copy(
            template_source,
            output_dir,  # Copier creates project_slug subdirectory from template
            data=copier_data,
            defaults=True,  # Use template defaults, overridden by our explicit data
            unsafe=False,  # No tasks in copier.yml anymore - we run them ourselves
            vcs_ref=resolved_ref,  # Use specified version if provided
            quiet=not is_verbose(),  # Silent unless --verbose
        )
    finally:
        if dev_template_dir is not None:
            dev_template_dir.cleanup()

    # Copier creates the project in output_dir/project_slug
    project_path = output_dir / template_context["project_slug"]

    # Store template version in answers file for future reference
    # Copier only writes fields defined in copier.yml, so we add this manually
    # This allows 'aegis update' to show "v0.4.1" instead of commit hash
    # Copier intermittently omits answers it considers "non-prompted" or
    # otherwise computed (observed for ``include_insights``, conditional
    # fields like ``worker_backend`` / ``scheduler_backend`` /
    # ``auth_oauth``, etc.). Patch any ``copier_data`` key Copier dropped
    # so downstream tooling (``aegis update``, ``aegis add-service``,
    # shared-file re-rendering) sees the project's real state.
    answers_file = project_path / AnswerKeys.ANSWERS_FILENAME
    if answers_file.exists():
        answers = yaml.safe_load(answers_file.read_text()) or {}

        template_version = copier_data.get("_template_version")
        if template_version:
            answers["_template_version"] = template_version

        # Backfill any key Copier failed to persist. Specifically guards
        # against ``add-service`` regenerating shared files like
        # ``app/core/config.py`` with stale service flags (issue #686 —
        # Failure B).
        for key, value in copier_data.items():
            if key.startswith("_"):
                continue
            if key not in answers:
                answers[key] = value

        answers_file.write_text(yaml.safe_dump(answers, default_flow_style=False))

    # Clean up unwanted component files based on selection
    # This must happen BEFORE post-generation tasks (which run linting on the remaining files)
    cleanup_components(project_path, copier_data)

    # Sweep any empty .py stubs produced by whole-file Jinja gates
    # (``{% if include_X %}...{% endif %}`` templates render as
    # whitespace when the gate is False). Must precede the lint pass
    # below; ``make fix`` chokes on modules referenced from
    # ``__init__.py`` that are empty. See issue #686 — Failure A.
    from .manual_updater import sweep_empty_stubs

    swept = sweep_empty_stubs(project_path)
    if swept:
        verbose_print(f"   Swept {len(swept)} empty stub file(s)")

    # Run post-generation tasks with explicit working directory control
    # This ensures consistent behavior with Cookiecutter
    include_auth = copier_data.get(AnswerKeys.AUTH, False)
    include_ai = copier_data.get(AnswerKeys.AI, False)
    include_insights = copier_data.get(AnswerKeys.INSIGHTS, False)
    include_blog = copier_data.get(AnswerKeys.BLOG, False)
    include_documents = copier_data.get(AnswerKeys.DOCUMENTS, False)
    ai_backend = copier_data.get(AnswerKeys.AI_BACKEND, StorageBackends.MEMORY)
    database_engine = copier_data.get(
        AnswerKeys.DATABASE_ENGINE, StorageBackends.SQLITE
    )

    # Type narrowing: ensure booleans for include_auth and include_ai
    is_auth_included: bool = include_auth is True
    is_ai_included: bool = include_ai is True

    # Type narrowing: ai_backend should always be a string, but narrow from Any
    ai_backend_str: str = str(ai_backend) if ai_backend else StorageBackends.MEMORY

    is_insights_included: bool = include_insights is True
    is_blog_included: bool = include_blog is True
    is_documents_included: bool = include_documents is True
    ai_needs_migrations = is_ai_included and ai_backend_str != StorageBackends.MEMORY
    needs_migration_files = (
        is_auth_included
        or ai_needs_migrations
        or is_insights_included
        or is_blog_included
    )
    # Only run migrations automatically for SQLite (file-based, no server needed)
    # PostgreSQL requires a running server, so skip auto-migration
    is_sqlite = database_engine == StorageBackends.SQLITE
    is_payment_included: bool = copier_data.get(AnswerKeys.PAYMENT, False) is True
    needs_migration_files = needs_migration_files or is_payment_included
    is_finance_included: bool = copier_data.get(AnswerKeys.FINANCE, False) is True
    needs_migration_files = needs_migration_files or is_finance_included
    # Scheduler component: job_execution history table. Postgres only — the
    # table lives in a ``scheduler`` schema (CREATE SCHEMA), which SQLite
    # can't run; SQLite scheduler stacks get the table via create_all.
    is_scheduler_included: bool = copier_data.get(AnswerKeys.SCHEDULER, False) is True
    scheduler_backend_str: str = str(
        copier_data.get(AnswerKeys.SCHEDULER_BACKEND, StorageBackends.MEMORY)
        or StorageBackends.MEMORY
    )
    scheduler_needs_migrations = (
        is_scheduler_included and scheduler_backend_str == StorageBackends.POSTGRES
    )
    needs_migration_files = needs_migration_files or scheduler_needs_migrations
    run_migrations = needs_migration_files and is_sqlite

    # Generate migrations for services that need them (always, regardless of engine)
    if needs_migration_files:
        # Get ai_voice from copier_data (it's a boolean after conversion)
        ai_voice_enabled: bool = copier_data.get(AnswerKeys.AI_VOICE, False) is True
        context = {
            AnswerKeys.AUTH: is_auth_included,
            AnswerKeys.AUTH_ORG: copier_data.get(AnswerKeys.AUTH_ORG, False) is True,
            AnswerKeys.AUTH_LEVEL: copier_data.get(
                AnswerKeys.AUTH_LEVEL, AuthLevels.BASIC
            ),
            AnswerKeys.AI: is_ai_included,
            AnswerKeys.AI_BACKEND: ai_backend_str,
            AnswerKeys.AI_VOICE: ai_voice_enabled,
            AnswerKeys.INSIGHTS: is_insights_included,
            AnswerKeys.INSIGHTS_PER_USER: copier_data.get(
                AnswerKeys.INSIGHTS_PER_USER, False
            )
            is True,
            AnswerKeys.BLOG: is_blog_included,
            AnswerKeys.DOCUMENTS: is_documents_included,
            AnswerKeys.PAYMENT: is_payment_included,
            AnswerKeys.FINANCE: is_finance_included,
            AnswerKeys.SCHEDULER: is_scheduler_included,
            AnswerKeys.SCHEDULER_BACKEND: scheduler_backend_str,
            # Finance tables live in a dedicated Postgres ``finance`` schema
            # (dropped on SQLite); the migration variant is engine-resolved.
            AnswerKeys.DATABASE_ENGINE: database_engine,
        }
        services = get_services_needing_migrations(context)
        if services:
            generated = generate_migrations_for_services(
                project_path, services, context
            )
            for migration_path in generated:
                print(f"Generated migration: {migration_path.name}")

    # AI needs seeding when using persistence backend AND sqlite (postgres needs running server)
    ai_needs_seeding = ai_needs_migrations and is_sqlite

    # Type narrowing: python_version from copier_data can be Any, so narrow to str | None
    python_version_value = copier_data.get("python_version")
    python_version_str: str | None = (
        python_version_value if isinstance(python_version_value, str) else None
    )

    # Skip LLM sync for postgres (requires running database server)
    should_skip_llm_sync = skip_llm_sync or not is_sqlite

    if reporter is not None:
        reporter.done("render")

    run_post_generation_tasks(
        project_path,
        include_migrations=run_migrations,
        python_version=python_version_str,
        seed_ai=ai_needs_seeding,
        skip_llm_sync=should_skip_llm_sync,
        project_slug=template_context["project_slug"],
        reporter=reporter,
    )

    # Initialize git repository for Copier updates
    # Copier requires a git-tracked project to perform updates

    try:
        subprocess.run(
            ["git", "init"],
            cwd=project_path,
            check=True,
            capture_output=True,
        )
        # Configure git user AFTER init (local config requires .git to exist)
        # This is needed for commits to work in CI environments
        subprocess.run(
            ["git", "config", "user.name", "Aegis Stack"],
            cwd=project_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "noreply@aegis-stack.dev"],
            cwd=project_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=project_path,
            check=True,
            capture_output=True,
        )
        # gc.auto=0: a plain commit may spawn a DETACHED background
        # ``git gc --auto`` that keeps repacking .git/objects after this
        # call returns — anything copying the fresh project (the test
        # cache, user scripts) then races loose-object deletion. The
        # user's own later git activity will gc normally.
        subprocess.run(
            [
                "git",
                "-c",
                "gc.auto=0",
                "commit",
                "-m",
                "Initial commit from Aegis Stack",
            ],
            cwd=project_path,
            check=True,
            capture_output=True,
        )
        verbose_print("Git repository initialized")
    except subprocess.CalledProcessError as e:
        print(f"Warning: Failed to initialize git repository: {e}")
        print("Run 'git init && git add . && git commit' manually")

    # Show docs/star links
    typer.echo()
    brand.muted(t("postgen.docs_link"))
    typer.echo()
    star = brand.accent_text("\u2605", bold=True)
    typer.echo(
        f"{star} {t('postgen.star_prompt')}\n  https://github.com/lbedner/aegis-stack"
    )

    # CRITICAL: Fix _src_path in .copier-answers.yml for future updates to work
    #
    # Problem: Copier stores a temp directory path during generation (e.g.,
    # /private/var/folders/...) which won't exist later when running updates.
    #
    # Solution: Update _src_path to point to the actual template repository:
    # - Development: git+file:// URL for local git repo
    # - Production: GitHub URL for remote repo
    #
    # IMPORTANT: We do NOT modify _commit - Copier sets this correctly when using
    # git+file:// URL. Manually overwriting _commit breaks Copier's 3-way merge
    # algorithm for updates. See: https://copier.readthedocs.io/en/stable/updating/
    try:
        answers_file = project_path / AnswerKeys.ANSWERS_FILENAME
        if answers_file.exists():
            with open(answers_file) as f:
                answers = yaml.safe_load(f)

            # Fix _src_path based on dev vs production mode
            # We already determined template_root above
            if is_git_repo(template_root):
                # Development mode: use local git repo
                answers["_src_path"] = f"git+file://{template_root}"
            else:
                # Production mode: use GitHub URL
                answers["_src_path"] = GITHUB_TEMPLATE_URL

            # Persist conditional auth fields (Copier may omit conditional
            # questions from answers file when values are provided via data)
            if copier_data.get(AnswerKeys.AUTH):
                answers[AnswerKeys.AUTH_LEVEL] = copier_data.get(
                    AnswerKeys.AUTH_LEVEL, "basic"
                )
                answers[AnswerKeys.AUTH_RBAC] = copier_data.get(
                    AnswerKeys.AUTH_RBAC, False
                )
                answers[AnswerKeys.AUTH_ORG] = copier_data.get(
                    AnswerKeys.AUTH_ORG, False
                )

            with open(answers_file, "w") as f:
                yaml.safe_dump(answers, f, default_flow_style=False, sort_keys=False)

            # Commit the updated .copier-answers.yml
            try:
                subprocess.run(
                    ["git", "add", AnswerKeys.ANSWERS_FILENAME],
                    cwd=project_path,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [
                        "git",
                        "commit",
                        "-m",
                        "Fix .copier-answers.yml _src_path for template updates",
                    ],
                    cwd=project_path,
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError:
                # If commit fails (e.g., no changes), that's OK
                pass

    except Exception:
        # If we can't fix _src_path, that's OK - project generation succeeded
        # but updates won't work. This can happen in non-git environments.
        pass

    return project_path


def is_copier_project(project_path: Path) -> bool:
    """
    Check if a project was generated with Copier.

    Args:
        project_path: Path to the project directory

    Returns:
        True if project has .copier-answers.yml file
    """
    answers_file = project_path / AnswerKeys.ANSWERS_FILENAME
    return answers_file.exists()


def load_copier_answers(project_path: Path) -> dict[str, Any]:
    """
    Load existing Copier answers from a project.

    Args:
        project_path: Path to the project directory

    Returns:
        Dictionary of Copier answers

    Raises:
        FileNotFoundError: If .copier-answers.yml doesn't exist
        yaml.YAMLError: If answers file is corrupted
    """
    answers_file = project_path / AnswerKeys.ANSWERS_FILENAME

    if not answers_file.exists():
        raise FileNotFoundError(
            f"No .copier-answers.yml found in {project_path}. "
            "This doesn't appear to be a Copier-generated project."
        )

    try:
        with open(answers_file) as f:
            answers = yaml.safe_load(f)
            if answers is None:
                return {}
            return answers
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Failed to parse .copier-answers.yml: {e}") from e


def update_with_copier(
    project_path: Path,
    additional_data: dict[str, Any] | None = None,
    conflict_mode: Literal["inline", "rej"] = "rej",
) -> None:
    """
    Update an existing Copier-generated project with new data.

    This function uses Copier's update mechanism to add new components
    or update existing project configuration.

    Args:
        project_path: Path to the existing project directory
        additional_data: New data to merge (e.g., {"include_scheduler": True})
        conflict_mode: How to handle conflicts - "rej" (separate files) or "inline" (markers)

    Raises:
        FileNotFoundError: If project doesn't have .copier-answers.yml
        Exception: If Copier update fails

    Example:
        # Add scheduler component to existing project
        update_with_copier(
            Path("my-project"),
            {"include_scheduler": True, "scheduler_backend": "memory"}
        )
    """
    # Validate it's a Copier project
    if not is_copier_project(project_path):
        raise FileNotFoundError(
            f"Project at {project_path} was not generated with Copier.\n"
            f"The 'aegis add' command only works with Copier-generated projects.\n"
            f"To add components, regenerate the project with the new components included."
        )

    # Load existing answers to validate state
    try:
        load_copier_answers(project_path)
    except yaml.YAMLError as e:
        raise Exception(
            f"Failed to read project configuration: {e}\n"
            f"The .copier-answers.yml file may be corrupted."
        ) from e

    # Prepare update data
    update_data = additional_data or {}

    # Run Copier update
    # NOTE: We do NOT pass src_path - Copier will read it from .copier-answers.yml
    # This is the key to making updates work!
    try:
        run_update(
            dst_path=str(project_path),
            data=update_data,
            defaults=True,  # Use existing answers as defaults
            overwrite=True,  # Allow overwriting files
            conflict=conflict_mode,  # How to handle conflicts
            unsafe=True,  # Allow running tasks (uv sync, make fix)
            vcs_ref="HEAD",  # Use latest template (no versioning needed yet)
        )
    except Exception as e:
        raise Exception(
            f"Failed to update project: {e}\n"
            f"This may be due to conflicts with manually modified files.\n"
            f"Check for .rej files in the project directory for details."
        ) from e
