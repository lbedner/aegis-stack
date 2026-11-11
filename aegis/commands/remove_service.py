"""
Remove service command implementation.

Removes services (auth, AI, etc.) from an existing Aegis Stack project.
"""

from pathlib import Path

import typer

from ..cli import brand
from ..cli.validation import (
    parse_comma_separated_list,
    validate_copier_project,
)
from ..constants import AnswerKeys, Messages
from ..core.component_utils import extract_base_service_name
from ..core.copier_manager import load_copier_answers
from ..core.manual_updater import ManualUpdater
from ..core.service_resolver import ServiceResolver
from ..core.services import SERVICES
from ..core.version_compatibility import validate_version_compatibility
from ..i18n import lazy_t, t


def _translated_service_desc(name: str, fallback: str) -> str:
    """Get translated description for a service, with fallback."""
    svc_key = f"service.{name}"
    result = t(svc_key)
    return result if result != svc_key else fallback


def remove_service_command(
    services: str | None = typer.Argument(
        None,
        help=lazy_t("remove_service.help_arg_services"),
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
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help=lazy_t("common.help_force"),
    ),
) -> None:
    """
    Remove services from an existing Aegis Stack project.

    This command removes service files and updates project configuration.
    WARNING: This operation deletes files and cannot be easily undone!

    Examples:

        - aegis remove-service auth

        - aegis remove-service auth,ai

        - aegis remove-service auth --project-path ../my-project

        - aegis --verbose remove-service auth (show detailed file operations)

    Note: Removing a service does not remove its required components.
    Use 'aegis remove' to remove components separately.

    Global options: Use --verbose/-v before the command for detailed output.
    """

    typer.echo(t("remove_service.title"))
    typer.echo("=" * 50)

    # Resolve project path
    target_path = Path(project_path).resolve()

    # Validate it's a Copier project
    validate_copier_project(target_path, "remove-service")

    typer.echo(t("remove_service.project", path=target_path))

    # Check version compatibility between CLI and project template
    validate_version_compatibility(
        target_path, command_name="remove-service", force=force
    )

    # Validate services argument or interactive mode
    if not interactive and not services:
        brand.error(t("remove_service.error_no_args"), err=True)
        typer.echo(f"   {t('remove_service.usage_hint')}", err=True)
        typer.echo(f"   {t('remove_service.interactive_hint')}", err=True)
        raise typer.Exit(1)

    # Interactive mode
    if interactive:
        if services:
            brand.warn(t("remove_service.interactive_ignores_args"))

        from ..cli.interactive import interactive_service_remove_selection

        selected_services = interactive_service_remove_selection(target_path)

        if not selected_services:
            brand.success(f"\n{t('remove_service.no_selected')}")
            raise typer.Exit(0)

        # Convert to comma-separated string for existing logic
        services = ",".join(selected_services)

        # Auto-confirm in interactive mode (user already confirmed during selection)
        yes = True

    # Parse and validate services
    assert services is not None  # Already validated by check above
    # Options name what was added, not what to remove: ai[sqlite,evals] is ai.
    selected_services = [
        extract_base_service_name(s)
        for s in parse_comma_separated_list(services, "service")
    ]

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
        brand.error(t("remove_service.validation_failed", error=e), err=True)
        raise typer.Exit(1)

    # Load existing project configuration
    try:
        existing_answers = load_copier_answers(target_path)
    except Exception as e:
        brand.error(t("remove_service.load_config_failed", error=e), err=True)
        raise typer.Exit(1)

    # Check which services are currently enabled
    not_enabled = []
    services_to_remove = []

    for service in selected_services:
        # Check if service is enabled
        include_key = AnswerKeys.include_key(service)
        if not existing_answers.get(include_key):
            not_enabled.append(service)
        else:
            services_to_remove.append(service)

    if not_enabled:
        typer.echo(t("remove_service.not_enabled", services=", ".join(not_enabled)))

    if not services_to_remove:
        brand.success(t("remove_service.nothing_to_remove"))
        raise typer.Exit(0)

    # Show what will be removed
    brand.warn(f"\n{t('remove_service.services_to_remove')}")
    for service in services_to_remove:
        if service in SERVICES:
            desc = _translated_service_desc(service, SERVICES[service].description)
            typer.echo(f"   • {service}: {desc}")

    # Warn about auth-specific data
    if AnswerKeys.SERVICE_AUTH in services_to_remove:
        brand.warn(f"\n{t('remove_service.auth_warning')}")
        typer.echo(f"   {t('remove_service.auth_delete_intro')}")
        typer.echo(f"   • {t('remove_service.auth_delete_endpoints')}")
        typer.echo(f"   • {t('remove_service.auth_delete_models')}")
        typer.echo(f"   • {t('remove_service.auth_delete_jwt')}")
        typer.echo(f"   {t('remove_service.auth_db_note')}")
        typer.echo()

    # Confirm before proceeding
    typer.echo()
    brand.warn(t("remove_service.warning_delete"))

    if not yes and not typer.confirm(t("remove_service.confirm")):
        brand.error(t("shared.operation_cancelled"))
        raise typer.Exit(0)

    # Remove services using ManualUpdater
    try:
        updater = ManualUpdater(target_path)

        for service in services_to_remove:
            typer.echo(f"\n{t('remove_service.removing', service=service)}")

            # Remove the service
            result = updater.remove_component(service)

            if not result.success:
                brand.error(
                    t(
                        "remove_service.failed_service",
                        service=service,
                        error=result.error_message,
                    ),
                    err=True,
                )
                raise typer.Exit(1)

            # Show results
            if result.files_deleted:
                brand.success(
                    f"   {t('remove_service.removed_files', count=len(result.files_deleted))}"
                )

        brand.success(f"\n{t('remove_service.success')}")

        # Provide next steps
        Messages.print_review_changes()
        Messages.print_next_steps()

        # Note about remaining components
        typer.echo(f"\n{t('remove_service.deps_not_removed')}")
        typer.echo(t("remove_service.deps_remove_hint"))

    except Exception as e:
        brand.error(f"\n{t('remove_service.failed', error=e)}", err=True)
        raise typer.Exit(1)
