"""
Remove command implementation.

Removes components from an existing Aegis Stack project using manual file deletion.
"""

from pathlib import Path

import typer

from ..cli import brand
from ..cli.validation import (
    parse_comma_separated_list,
    validate_copier_project,
)
from ..constants import AnswerKeys, ComponentNames, Messages, StorageBackends
from ..core.components import COMPONENTS, CORE_COMPONENTS
from ..core.copier_manager import load_copier_answers
from ..core.dependency_resolver import DependencyResolver
from ..core.manual_updater import ManualUpdater
from ..core.plugins.compat import reverse_dependents
from ..core.plugins.discovery import discover_plugins
from ..core.services import SERVICES
from ..core.version_compatibility import validate_version_compatibility
from ..i18n import lazy_t, t
from .add import _resolve_plugin


def _uninstall_plugin(
    name: str,
    target_path: Path,
    yes: bool,
    force: bool,
) -> None:
    """Run the full ``aegis remove <plugin>`` flow for an external plugin.

    Mirrors the component remove flow's structure but routes through
    ``ManualUpdater.remove_plugin`` and adds a reverse-dependency check
    that the existing ``remove-service`` lacks.
    """
    # The module name locates the plugin's template tree, so remove can
    # take out everything add rendered, not only what the manifest lists.
    resolved = _resolve_plugin(name)
    if resolved is None:
        brand.error(f"Plugin not found: {name!r}", err=True)
        raise typer.Exit(1)
    plugin_spec, plugin_module_name = resolved

    answers = load_copier_answers(target_path)

    # Reverse-dep check: refuse to remove a plugin that other installed
    # specs depend on. ``--force`` bypasses (escape hatch for known
    # situations the user has already reasoned about). Candidates span
    # services, components, and external plugins — components can
    # carry ``required_plugins`` too, so leaving them out would let a
    # silent-broken removal slip through.
    candidates: list = (
        list(SERVICES.values()) + list(COMPONENTS.values()) + list(discover_plugins())
    )
    dependents = reverse_dependents(plugin_spec.name, candidates, answers)
    if dependents and not force:
        brand.error(
            f"Cannot remove {plugin_spec.name!r}: still required by "
            f"{', '.join(repr(d) for d in dependents)}",
            err=True,
        )
        typer.echo(
            "   Remove dependents first, or pass --force to override.",
            err=True,
        )
        raise typer.Exit(1)
    if dependents and force:
        brand.warn(
            f"Forcing removal despite reverse dependents: "
            f"{', '.join(repr(d) for d in dependents)}"
        )

    typer.echo(f"\n{t('remove.plugin_removing', name=plugin_spec.name)}")
    if not yes and not typer.confirm(
        t("remove.plugin_confirm", name=plugin_spec.name), default=False
    ):
        brand.error(t("shared.operation_cancelled"))
        raise typer.Exit(0)

    updater = ManualUpdater(target_path)
    result = updater.remove_plugin(plugin_spec, plugin_module_name)

    if not result.success:
        brand.error(f"\nPlugin remove failed: {result.error_message}", err=True)
        raise typer.Exit(1)

    brand.success(f"\n{t('remove.plugin_success', name=plugin_spec.name)}")
    if plugin_spec.migrations:
        typer.echo(
            "   Its tables were exported to <STORAGE_ROOT>/plugin-exports/ and "
            "dropped; adding the plugin again restores them. A deployed "
            "database does the same when it applies the new revision."
        )


def _translated_desc(name: str, fallback: str) -> str:
    """Get translated description for a component, with fallback."""
    key = f"component.{name}"
    result = t(key)
    return result if result != key else fallback


def remove_command(
    components: str | None = typer.Argument(
        None,
        help=lazy_t("remove.help_arg_components"),
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help=lazy_t("common.help_interactive_components"),
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
    Remove components from an existing Aegis Stack project.

    This command removes component files and updates project configuration.
    WARNING: This operation deletes files and cannot be easily undone!

    Examples:
        - aegis remove scheduler
        - aegis remove worker,database
        - aegis remove scheduler --project-path ../my-project
        - aegis --verbose remove worker (show detailed file operations)

    Note: Core components (backend, frontend) cannot be removed.

    Global options: Use --verbose/-v before the command for detailed output.
    """

    typer.echo(t("remove.title"))
    typer.echo("=" * 50)

    # Resolve project path
    target_path = Path(project_path).resolve()

    # Validate it's a Copier project
    validate_copier_project(target_path, "remove")

    typer.echo(t("remove.project", path=target_path))

    # Check version compatibility between CLI and project template
    validate_version_compatibility(target_path, command_name="remove", force=force)

    # Validate components argument or interactive mode
    if not interactive and not components:
        brand.error(t("remove.error_no_args"), err=True)
        typer.echo(f"   {t('remove.usage_hint')}", err=True)
        typer.echo(f"   {t('remove.interactive_hint')}", err=True)
        raise typer.Exit(1)

    # Plugin / service dispatch — single-name args only. Services
    # forward to the existing remove-service implementation (Phase 2
    # of #771: unify the entry point, defer the implementation-merge).
    if components and "," not in components:
        if _resolve_plugin(components) is not None:
            _uninstall_plugin(components, target_path, yes, force)
            return

        # Bracket-tolerant base extraction for symmetry with
        # ``aegis add`` — users sometimes type bracket syntax even on
        # remove out of habit.
        service_base = components.split("[", 1)[0].strip()
        if service_base in SERVICES:
            from .remove_service import remove_service_command

            remove_service_command(
                services=components,
                interactive=False,
                project_path=str(target_path),
                yes=yes,
                force=force,
            )
            return

    # Interactive mode
    if interactive:
        if components:
            brand.warn(t("shared.interactive_ignores_args"))

        from ..cli.interactive import interactive_component_remove_selection

        selected_components = interactive_component_remove_selection(target_path)

        if not selected_components:
            brand.success(f"\n{t('remove.no_selected')}")
            raise typer.Exit(0)

        # Convert to comma-separated string for existing logic
        components = ",".join(selected_components)

        # Auto-confirm in interactive mode (user already confirmed during selection)
        yes = True

    # Parse and validate components
    assert components is not None  # Already validated by check above
    selected_components = parse_comma_separated_list(components, "component")

    # Validate components exist
    try:
        # Use the same validation logic as init command
        errors = DependencyResolver.validate_components(selected_components)
        if errors:
            for error in errors:
                brand.error(f"{error}", err=True)
            raise typer.Exit(1)

    except Exception as e:
        brand.error(t("remove.validation_failed", error=e), err=True)
        raise typer.Exit(1)

    # Load existing project configuration
    try:
        existing_answers = load_copier_answers(target_path)
    except Exception as e:
        brand.error(t("remove.load_config_failed", error=e), err=True)
        raise typer.Exit(1)

    # Check which components are currently enabled
    not_enabled = []
    components_to_remove = []

    for component in selected_components:
        # Check if component is core (cannot be removed)
        if component in CORE_COMPONENTS:
            brand.warn(t("remove.cannot_remove_core", component=component))
            continue

        # Check if component is enabled
        include_key = AnswerKeys.include_key(component)
        if not existing_answers.get(include_key):
            not_enabled.append(component)
        else:
            components_to_remove.append(component)

    if not_enabled:
        typer.echo(t("remove.not_enabled", components=", ".join(not_enabled)))

    if not components_to_remove:
        brand.success(t("remove.nothing_to_remove"))
        raise typer.Exit(0)

    # Auto-remove redis if worker is being removed (redis has no standalone functionality)
    # Don't remove redis if cache component is using it
    if (
        ComponentNames.WORKER in components_to_remove
        and ComponentNames.REDIS not in components_to_remove
        and existing_answers.get(AnswerKeys.REDIS)
        and not existing_answers.get(
            AnswerKeys.CACHE
        )  # Future: cache component may use redis
    ):
        components_to_remove.append(ComponentNames.REDIS)
        typer.echo(t("remove.auto_remove_redis"))

    # Check for scheduler with sqlite backend - warn about persistence
    if ComponentNames.SCHEDULER in components_to_remove:
        scheduler_backend = existing_answers.get(AnswerKeys.SCHEDULER_BACKEND)
        if scheduler_backend == StorageBackends.SQLITE:
            brand.warn(f"\n{t('remove.scheduler_persistence_warn')}")
            typer.echo(f"   {t('remove.scheduler_persistence_detail')}")
            typer.echo(f"   {t('remove.scheduler_db_remains')}")
            typer.echo()
            typer.echo(f"   {t('remove.scheduler_keep_hint')}")
            typer.echo(f"   {t('remove.scheduler_remove_hint')}")
            typer.echo()

    # Show what will be removed
    brand.warn(f"\n{t('remove.components_to_remove')}")
    for component in components_to_remove:
        if component in COMPONENTS:
            desc = _translated_desc(component, COMPONENTS[component].description)
            typer.echo(f"   • {component}: {desc}")

    # Confirm before proceeding
    typer.echo()
    brand.warn(t("remove.warning_delete"))
    typer.echo(f"   {t('remove.commit_hint')}")
    typer.echo()

    if not yes and not typer.confirm(t("remove.confirm")):
        brand.error(t("shared.operation_cancelled"))
        raise typer.Exit(0)

    # Run manual removal for each component
    try:
        updater = ManualUpdater(target_path)

        # Remove each component sequentially
        for component in components_to_remove:
            typer.echo(f"\n{t('remove.removing', component=component)}")

            # Remove the component
            result = updater.remove_component(component)

            if not result.success:
                brand.error(
                    t(
                        "remove.failed_component",
                        component=component,
                        error=result.error_message,
                    ),
                    err=True,
                )
                raise typer.Exit(1)

            # Show results
            if result.files_deleted:
                brand.success(
                    f"   {t('remove.removed_files', count=len(result.files_deleted))}"
                )

        brand.success(f"\n{t('remove.success')}")
        Messages.print_next_steps()

    except Exception as e:
        brand.error(f"\n{t('remove.failed', error=e)}", err=True)
        raise typer.Exit(1)
