"""
Add service command implementation.

Adds services (auth, AI, etc.) to an existing Aegis Stack project using Copier's update mechanism.
"""

from pathlib import Path

import typer

from ..cli import brand
from ..cli.callbacks import _split_service_list
from ..cli.utils import detect_scheduler_backend
from ..cli.validation import (
    validate_copier_project,
    validate_git_repository,
)
from ..constants import (
    AIProviders,
    AnswerKeys,
    AuthLevels,
    ComponentNames,
    Messages,
    StorageBackends,
)
from ..core.auth_service_parser import (
    is_auth_service_with_options,
    parse_auth_service_config,
)
from ..core.component_utils import (
    extract_base_component_name,
    extract_base_service_name,
)
from ..core.components import COMPONENTS, CORE_COMPONENTS
from ..core.copier_manager import load_copier_answers
from ..core.manual_updater import ManualUpdater
from ..core.migration_generator import (
    MIGRATION_SPECS,
    bootstrap_alembic,
    generate_migration,
    get_services_needing_migrations,
    service_has_migration,
)
from ..core.project_map import render_project_map
from ..core.service_resolver import ServiceResolver
from ..core.services import SERVICES, get_service_dependencies
from ..i18n import lazy_t, t


def _translated_component_desc(name: str, fallback: str) -> str:
    """Get translated description for a component, with fallback."""
    key = f"component.{name}"
    result = t(key)
    return result if result != key else fallback


def _translated_service_desc(name: str, fallback: str) -> str:
    """Get translated description for a service, with fallback."""
    key = f"service.{name}"
    result = t(key)
    return result if result != key else fallback


def add_service_command(
    services: str | None = typer.Argument(
        None,
        help=lazy_t("add_service.help_arg_services"),
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help=lazy_t("common.help_interactive_services"),
    ),
    project_path: str = typer.Option(
        ".",
        "--project-path",
        "-p",
        help=lazy_t("common.help_project_path_full"),
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help=lazy_t("common.help_yes")),
) -> None:
    """
    Add services to an existing Aegis Stack project.

    This command uses Copier's update mechanism to add new services (auth, AI, etc.)
    to a project that was generated with 'aegis init'.

    Examples:

        - aegis add-service auth

        - aegis add-service auth,ai

        - aegis add-service auth --project-path ../my-project

    Note: This command only works with projects generated using Copier
    (the default since v0.2.0). Services may auto-add required components.
    """

    typer.echo(t("add_service.title"))
    typer.echo("=" * 50)

    # Resolve project path
    target_path = Path(project_path).resolve()

    # Validate it's a Copier project
    validate_copier_project(target_path, "add-service")

    typer.echo(t("add_service.project", path=target_path))

    # Validate services argument or interactive mode
    if not interactive and not services:
        brand.error(t("add_service.error_no_args"), err=True)
        typer.echo(f"   {t('add_service.usage_hint')}", err=True)
        typer.echo(f"   {t('add_service.interactive_hint')}", err=True)
        raise typer.Exit(1)

    # Interactive mode
    if interactive:
        if services:
            brand.warn(t("add_service.interactive_ignores_args"))

        from ..cli.interactive import interactive_service_selection

        selected_services = interactive_service_selection(target_path)

        if not selected_services:
            brand.success(f"\n{t('add_service.no_selected')}")
            raise typer.Exit(0)

        # Convert to comma-separated string for existing logic
        services = ",".join(selected_services)

        # Auto-confirm in interactive mode
        yes = True

    # Verify project is in a git repository (required for Copier updates)
    validate_git_repository(target_path)

    # Parse services (respecting bracket syntax like ai[langchain,sqlite])
    assert services is not None  # Already validated by check above
    selected_services = _split_service_list(services)

    # Create mapping: full name -> base name (for bracket syntax like ai[langchain,sqlite])
    # This is done once and used throughout to keep things DRY
    service_base_map: dict[str, str] = {
        s: extract_base_service_name(s) for s in selected_services
    }

    # Validate services exist
    try:
        errors = ServiceResolver.validate_services(selected_services)
        if errors:
            for error in errors:
                brand.error(f"{error}", err=True)
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        brand.error(t("add_service.validation_failed", error=e), err=True)
        raise typer.Exit(1)

    # Load existing project configuration
    try:
        existing_answers = load_copier_answers(target_path)
    except Exception as e:
        brand.error(t("add_service.load_config_failed", error=e), err=True)
        raise typer.Exit(1)

    # Check which services are already enabled
    already_enabled = []
    for service in selected_services:
        # Check if service is already enabled in answers (use base name for bracket syntax)
        base_service = service_base_map[service]
        include_key = AnswerKeys.include_key(base_service)
        if existing_answers.get(include_key) is True:
            # Special case: auth level upgrades (basic → rbac → org)
            if base_service == AnswerKeys.SERVICE_AUTH and is_auth_service_with_options(
                service
            ):
                auth_config = parse_auth_service_config(service)
                current_level = existing_answers.get(
                    AnswerKeys.AUTH_LEVEL, AuthLevels.BASIC
                )
                level_order = {
                    AuthLevels.BASIC: 0,
                    AuthLevels.RBAC: 1,
                    AuthLevels.ORG: 2,
                }
                if level_order.get(auth_config.level, 0) > level_order.get(
                    current_level, 0
                ):
                    # Upgrading auth level — don't skip
                    continue
            already_enabled.append(service)

    if already_enabled:
        typer.echo(
            t("add_service.already_enabled", services=", ".join(already_enabled))
        )

    # Filter out already enabled services
    services_to_add = [s for s in selected_services if s not in already_enabled]

    if not services_to_add:
        brand.success(t("add_service.all_enabled"))
        raise typer.Exit(0)

    # Handle AI service interactive configuration
    # We need to check if AI service is being added and prompt for configuration
    ai_config: dict[str, str | list[str] | bool] = {}
    for i, service in enumerate(services_to_add):
        base_service = service_base_map[service]
        if base_service == AnswerKeys.SERVICE_AI:
            if not service.startswith("ai["):
                # AI service without bracket syntax - prompt for configuration
                from ..cli.interactive import interactive_ai_service_config

                backend, framework, providers, rag_enabled, voice_enabled = (
                    interactive_ai_service_config(base_service)
                )

                # Store config for later use
                ai_config["backend"] = backend
                ai_config["framework"] = framework
                ai_config["providers"] = providers
                ai_config["rag_enabled"] = rag_enabled
                ai_config["voice_enabled"] = voice_enabled

                # Build bracket syntax and update the service entry
                options = [backend, framework] + providers
                if rag_enabled:
                    options.append("rag")
                if voice_enabled:
                    options.append("voice")
                service_string = f"{base_service}[{','.join(options)}]"
                services_to_add[i] = service_string

                # Update the mapping with the new full service name
                service_base_map[service_string] = base_service
                # Remove old mapping entry
                del service_base_map[service]
            else:
                # AI service with bracket syntax - parse backend from options
                # Format: ai[backend,framework,provider1,provider2,...]
                from ..core.ai_service_parser import parse_ai_service_config

                config = parse_ai_service_config(service)
                ai_config["backend"] = config.backend
                ai_config["framework"] = config.framework
                ai_config["providers"] = config.providers

    # Resolve service dependencies to components
    try:
        required_components, _ = ServiceResolver.resolve_service_dependencies(
            services_to_add
        )
    except ValueError as e:
        brand.error(t("add_service.resolve_failed", error=e), err=True)
        raise typer.Exit(1)

    # If AI service selected SQLite backend, ensure database is in required components
    if (
        ai_config.get("backend") == StorageBackends.SQLITE
        and ComponentNames.DATABASE not in required_components
    ):
        required_components.append(ComponentNames.DATABASE)

    # Check which components are already enabled
    enabled_components = []
    missing_components = []

    for component in required_components:
        include_key = AnswerKeys.include_key(component)
        if existing_answers.get(include_key) is True or component in CORE_COMPONENTS:
            enabled_components.append(component)
        else:
            missing_components.append(component)

    # Show what will be added
    brand.accent(f"\n{t('add_service.services_to_add')}", bold=True)
    for service in services_to_add:
        base_service = service_base_map[service]
        if base_service in SERVICES:
            desc = _translated_service_desc(
                base_service, SERVICES[base_service].description
            )
            typer.echo(f"   • {service}: {desc}")

    # Show component requirements
    if missing_components:
        brand.warn(f"\n{t('add_service.required_components')}")
        for component in missing_components:
            if component in COMPONENTS:
                desc = _translated_component_desc(
                    component, COMPONENTS[component].description
                )
                typer.echo(f"   • {component}: {desc}")

    if enabled_components:
        # Filter out core components from display
        non_core_enabled = [c for c in enabled_components if c not in CORE_COMPONENTS]
        if non_core_enabled:
            brand.success(
                f"\n{t('add_service.already_have_components', components=', '.join(non_core_enabled))}"
            )

    # Confirm before proceeding
    typer.echo()
    if not yes and not typer.confirm(t("add_service.confirm"), default=True):
        brand.error(t("shared.operation_cancelled"))
        raise typer.Exit(0)

    # Prepare update data for ManualUpdater
    update_data: dict[str, bool | str] = {}

    # Add service flags (use base service name to handle bracket syntax like ai[sqlite])
    for service in services_to_add:
        base_service = service_base_map[service]
        include_key = AnswerKeys.include_key(base_service)
        update_data[include_key] = True

    # Add missing component flags (use base component name to handle bracket syntax)
    for component in missing_components:
        base_component = extract_base_component_name(component)
        include_key = AnswerKeys.include_key(base_component)
        update_data[include_key] = True

    # Add services using ManualUpdater
    try:
        updater = ManualUpdater(target_path)

        # Add missing components first
        for component in missing_components:
            brand.accent(f"\n{t('add_service.adding_component', component=component)}")

            # Prepare component-specific data
            component_data: dict[str, bool | str] = {}

            # Handle scheduler backend if needed
            if component == ComponentNames.SCHEDULER:
                scheduler_backend = detect_scheduler_backend([component])
                component_data[AnswerKeys.SCHEDULER_BACKEND] = scheduler_backend
                component_data[AnswerKeys.SCHEDULER_WITH_PERSISTENCE] = (
                    scheduler_backend == StorageBackends.SQLITE
                )
            elif component == ComponentNames.DATABASE:
                component_data[AnswerKeys.DATABASE_ENGINE] = StorageBackends.SQLITE

            # Add the component
            result = updater.add_component(component, component_data)

            if not result.success:
                brand.error(
                    t(
                        "add_service.failed_component",
                        component=component,
                        error=result.error_message,
                    ),
                    err=True,
                )
                raise typer.Exit(1)

            if result.files_modified:
                brand.success(
                    f"   {t('add_service.added_files', count=len(result.files_modified))}"
                )
            if result.files_skipped:
                brand.warn(
                    f"   {t('add_service.skipped_files', count=len(result.files_skipped))}"
                )
            if result.files_deleted:
                brand.accent(
                    f"   Cleaned {len(result.files_deleted)} empty stub file(s)"
                )
            if result.shared_files_need_manual_merge:
                brand.warn(
                    f"   {t('add_service.preserved_files', count=len(result.shared_files_need_manual_merge))}"
                )

        # Now add each service sequentially
        for service in services_to_add:
            brand.accent(f"\n{t('add_service.adding_service', service=service)}")

            # Prepare service-specific data
            service_data: dict[str, bool | str] = {}

            # Get base service name (strips variant syntax like [langchain,sqlite])
            base_service = service_base_map[service]

            # For auth service, pass auth level data
            if base_service == AnswerKeys.SERVICE_AUTH and is_auth_service_with_options(
                service
            ):
                auth_config = parse_auth_service_config(service)
                service_data[AnswerKeys.AUTH_LEVEL] = auth_config.level
                service_data[AnswerKeys.AUTH_RBAC] = auth_config.level in (
                    AuthLevels.RBAC,
                    AuthLevels.ORG,
                )
                service_data[AnswerKeys.AUTH_ORG] = auth_config.level == AuthLevels.ORG

            # For AI service, use the captured configuration
            if base_service == AnswerKeys.SERVICE_AI:
                # Use providers from interactive config, or default to openai
                providers = ai_config.get("providers", [AIProviders.OPENAI])
                if isinstance(providers, list):
                    service_data[AnswerKeys.AI_PROVIDERS] = ",".join(providers)
                else:
                    service_data[AnswerKeys.AI_PROVIDERS] = str(providers)

                # Set backend and framework for pyproject.toml regeneration
                # This ensures alembic is included when sqlite backend is selected
                backend = ai_config.get("backend", StorageBackends.MEMORY)
                framework = ai_config.get("framework", "pydantic-ai")
                # Ensure backend and framework are strings (not lists from ai_config)
                if isinstance(backend, str):
                    service_data[AnswerKeys.AI_BACKEND] = backend
                if isinstance(framework, str):
                    service_data[AnswerKeys.AI_FRAMEWORK] = framework

            # For insights service, pass source flags
            if base_service == AnswerKeys.SERVICE_INSIGHTS:
                from ..core.insights_service_parser import (
                    DEFAULT_SOURCES,
                    is_insights_service_with_options,
                    parse_insights_service_config,
                )

                if is_insights_service_with_options(service):
                    insights_config = parse_insights_service_config(service)
                    sources = insights_config.sources
                else:
                    sources = DEFAULT_SOURCES
                service_data[AnswerKeys.INSIGHTS_GITHUB] = "github" in sources
                service_data[AnswerKeys.INSIGHTS_PYPI] = "pypi" in sources
                service_data[AnswerKeys.INSIGHTS_PLAUSIBLE] = "plausible" in sources
                service_data[AnswerKeys.INSIGHTS_REDDIT] = "reddit" in sources

            # Add the service (services are added like components)
            # Use base_service for file lookup, not the full variant name
            result = updater.add_component(base_service, service_data)

            if not result.success:
                brand.error(
                    t(
                        "add_service.failed_service",
                        service=service,
                        error=result.error_message,
                    ),
                    err=True,
                )
                raise typer.Exit(1)

            # Show results
            if result.files_modified:
                brand.success(
                    f"   {t('add_service.added_files', count=len(result.files_modified))}"
                )
            if result.files_skipped:
                brand.warn(
                    f"   {t('add_service.skipped_files', count=len(result.files_skipped))}"
                )
            if result.files_deleted:
                brand.accent(
                    f"   Cleaned {len(result.files_deleted)} empty stub file(s)"
                )
            if result.shared_files_need_manual_merge:
                brand.warn(
                    f"   {t('add_service.preserved_files', count=len(result.shared_files_need_manual_merge))}"
                )

        # Generate migrations for services that need them
        for service in services_to_add:
            base_service = service_base_map[service]
            if base_service not in MIGRATION_SPECS:
                continue

            # AI service only needs migrations with SQLite backend (not memory)
            if base_service == AnswerKeys.SERVICE_AI:
                ai_backend = ai_config.get("backend", StorageBackends.MEMORY)
                if ai_backend == StorageBackends.MEMORY:
                    continue  # Skip migrations for memory backend

            alembic_dir = target_path / "alembic"
            if not alembic_dir.exists():
                brand.accent(f"\n{t('add_service.bootstrap_alembic')}")
                created = bootstrap_alembic(
                    target_path, updater.jinja_env, updater.answers
                )
                for f in created:
                    typer.echo(f"   {t('add_service.created_file', file=f)}")

            if not service_has_migration(target_path, base_service):
                migration_path = generate_migration(target_path, base_service)
                if migration_path:
                    brand.success(
                        f"   {t('add_service.generated_migration', name=migration_path.name)}"
                    )

        # For auth level upgrades, generate any missing level-specific migrations
        # (e.g., auth_rbac, auth_org, auth_tokens)
        updated_answers = updater.answers
        needed_migrations = get_services_needing_migrations(updated_answers)
        for migration_service in needed_migrations:
            if migration_service in MIGRATION_SPECS and not service_has_migration(
                target_path, migration_service
            ):
                migration_path = generate_migration(target_path, migration_service)
                if migration_path:
                    brand.success(
                        f"   {t('add_service.generated_migration', name=migration_path.name)}"
                    )

        # Auto-run migrations for services that need them
        # Exclude AI service with memory backend (doesn't need migrations)
        ai_needs_migrations = (
            ai_config.get("backend", StorageBackends.MEMORY) != StorageBackends.MEMORY
        )
        services_with_migrations = [
            s
            for s in services_to_add
            if service_base_map[s] in MIGRATION_SPECS
            and (service_base_map[s] != AnswerKeys.SERVICE_AI or ai_needs_migrations)
        ]
        if services_with_migrations:
            brand.accent(f"\n{t('add_service.applying_migrations')}")
            from ..core.post_gen_tasks import run_migrations

            migration_success = run_migrations(target_path, include_migrations=True)

            if not migration_success:
                brand.warn(t("add_service.migration_failed"))

            # Seed the AI fixtures (LLM catalog + default agent) when the
            # ai service just landed with a persistence backend; mirrors
            # the init path so an added ai service starts with the same
            # seeded registry a fresh project gets.
            ai_added = any(
                service_base_map[s] == AnswerKeys.SERVICE_AI for s in services_to_add
            )
            if migration_success and ai_added and ai_needs_migrations:
                from ..core.post_gen_tasks import seed_ai_fixtures

                seed_ai_fixtures(target_path)

        brand.success(f"\n{t('add_service.success')}")

        # Show project map with newly added services + auto-added components highlighted
        base_services_for_highlight = [service_base_map[s] for s in services_to_add]
        # Normalize missing_components to base names so highlight and uses are consistent
        normalized_missing = {
            extract_base_component_name(c) for c in missing_components
        }
        all_newly_added = base_services_for_highlight + list(normalized_missing)

        # Build uses dict for existing dependencies (components that already existed)
        uses: dict[str, list[str]] = {}
        for service in services_to_add:
            base_service = service_base_map[service]
            service_deps = get_service_dependencies(base_service)
            for dep in service_deps:
                # Only show uses for components that already existed (not newly added)
                if dep not in normalized_missing and dep not in CORE_COMPONENTS:
                    uses.setdefault(dep, []).append(base_service)

        typer.echo()
        render_project_map(target_path, highlight=all_newly_added, uses=uses)

        # Provide next steps
        if len(services_to_add) > 0 or len(missing_components) > 0:
            Messages.print_review_changes()

        Messages.print_next_steps()

        # Service-specific guidance (use base service names for comparison)
        base_services_added = [service_base_map[s] for s in services_to_add]

        if AnswerKeys.SERVICE_AUTH in base_services_added:
            project_slug = existing_answers.get(AnswerKeys.PROJECT_SLUG, "my-project")
            brand.accent(f"\n{t('add_service.auth_setup')}", bold=True)
            cmd = typer.style(f"{project_slug} auth create-test-users", bold=True)
            typer.echo(t("add_service.auth_create_users", cmd=cmd))
            url = typer.style("http://localhost:8000/docs", bold=True)
            typer.echo(t("add_service.auth_view_routes", url=url))

        if AnswerKeys.SERVICE_AI in base_services_added:
            project_slug = existing_answers.get(AnswerKeys.PROJECT_SLUG, "my-project")
            brand.accent(f"\n{t('add_service.ai_setup')}", bold=True)
            typer.echo(
                t(
                    "add_service.ai_set_provider",
                    env_var=typer.style("AI_PROVIDER", bold=True),
                )
            )
            typer.echo(
                t(
                    "add_service.ai_set_api_key",
                    env_var=typer.style("OPENAI_API_KEY", bold=True),
                )
            )
            cmd = typer.style(f"{project_slug} ai chat", bold=True)
            typer.echo(t("add_service.ai_test_cli", cmd=cmd))

    except Exception as e:
        brand.error(f"\n{t('add_service.failed', error=e)}", err=True)
        raise typer.Exit(1)
