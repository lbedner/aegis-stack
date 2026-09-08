"""
Add command implementation.

Adds components to an existing Aegis Stack project using Copier's update mechanism.
"""

from pathlib import Path

import typer

from ..cli import brand
from ..cli.utils import detect_scheduler_backend
from ..cli.validation import (
    parse_comma_separated_list,
    validate_copier_project,
    validate_git_repository,
)
from ..constants import (
    AnswerKeys,
    ComponentNames,
    Messages,
    StorageBackends,
    WorkerBackends,
)
from ..core.component_utils import extract_base_component_name, extract_engine_info
from ..core.components import COMPONENTS, CORE_COMPONENTS
from ..core.copier_manager import load_copier_answers
from ..core.dependency_resolver import DependencyResolver
from ..core.manual_updater import ManualUpdater
from ..core.option_spec import is_spec_with_options, parse_options
from ..core.plugins.discovery import discover_plugins
from ..core.plugins.naming import dist_name
from ..core.plugins.spec import PluginSpec
from ..core.project_map import render_project_map
from ..core.services import SERVICES
from ..core.version_compatibility import validate_version_compatibility
from ..i18n import lazy_t, t


def _strip_brackets(spec_str: str) -> str:
    """Pull the base name out of ``foo[opt1,opt2]``.

    ``extract_base_component_name`` is stricter and rejects bracket
    contents that contain commas or whitespace — that's intentional
    for component names but too narrow for plugins/services with
    bracket-syntax options (``ai[langchain,openai]`` is valid).
    Splitting on the literal ``[`` is the simplest tolerant variant.
    """
    return spec_str.split("[", 1)[0].strip()


def _resolve_plugin(spec_str: str) -> tuple[PluginSpec, str] | None:
    """Match ``spec_str`` (with or without bracket options) against a
    discovered external plugin.

    Returns ``(spec, module_name)`` where ``module_name`` is the
    importable Python package (e.g. ``"aegis_stack_scraper"``) — the
    spec's ``name`` is a logical identifier and may differ. The module
    name is what the template resolver and the runtime importer need.
    Returns ``None`` if no plugin matches.

    Module-name resolution iterates entry points and re-loads each
    spec until the names match. ``ep.name`` and ``spec.name`` are
    free to differ, so matching on entry-point name alone misses
    cases where a plugin author exposes ``my_pkg = ...`` but the
    spec says ``name="scraper"``.
    """
    from importlib.metadata import entry_points

    base_name = _strip_brackets(spec_str)
    for plugin in discover_plugins():
        if plugin.name != base_name:
            continue
        for ep in entry_points(group="aegis.plugins"):
            # Mirror ``_load_plugin_spec`` in ``plugins.discovery``: the
            # entry point can resolve to either a factory callable
            # (``"pkg:get_spec"``) or a pre-built ``PluginSpec`` instance
            # (``"pkg:SPEC"``). Calling unconditionally would crash on
            # the instance shape and fall through to the plugin.name
            # fallback below — which usually picks the wrong module
            # name when the package directory differs from the spec
            # name (e.g. ``aegis_stack_scraper`` vs ``scraper``).
            try:
                loader = ep.load()
                ep_spec = loader() if callable(loader) else loader
            except Exception:
                continue
            if getattr(ep_spec, "name", None) == plugin.name:
                # ``ep.value`` is "module.path:attr" — the module path
                # is everything before the colon, top-level package is
                # everything before the first dot.
                module_name = ep.value.split(":")[0].split(".")[0]
                return (plugin, module_name)
        # Fallback: no entry point matched (shouldn't happen — discovery
        # populated this spec from one). Use plugin.name as module name;
        # if it's wrong, template resolution will surface a clear
        # ``ModuleNotFoundError``.
        return (plugin, plugin.name)
    return None


def _install_plugin(
    spec_str: str,
    target_path: Path,
    yes: bool,
    force: bool = False,
    *,
    run_post_gen: bool = True,
) -> None:
    """Run the full ``aegis add <plugin>`` flow for an external plugin.

    Mirrors the component flow's structure (validate, confirm, render,
    summarize) but the rendering goes through ``ManualUpdater.add_plugin``,
    which appends a ``_plugins`` entry, regenerates shared files, and
    drops the plugin's own template tree.

    The ``force`` flag bypasses the aegis-version compatibility check
    (#777). The user already confirmed they understand the risk;
    we let the install proceed.

    The ``run_post_gen`` keyword controls the trailing ``uv sync`` /
    ``make fix`` pass. The top-level CLI invocation keeps the default
    ``True``; recursive calls (a plugin dep that's itself a plugin)
    pass ``False`` so the outermost call runs sync exactly once for
    the entire dependency tree. Without this, a target plugin with
    N transitive deps would do N+1 sync passes.
    """
    from ..core.plugins.compat import check_aegis_version_compat

    resolved = _resolve_plugin(spec_str)
    if resolved is None:
        # Caller should have checked first; defensive guard.
        brand.error(
            f"Plugin not found: {extract_base_component_name(spec_str)!r}", err=True
        )
        raise typer.Exit(1)

    plugin_spec, plugin_module_name = resolved

    # Aegis-version compat (#777). Plugins built for a different CLI
    # major may rely on internals that moved or were renamed; we'd
    # rather refuse the install than ship a broken project. ``--force``
    # bypasses for users who know what they're doing.
    compatible, error_msg = check_aegis_version_compat(plugin_spec)
    if not compatible:
        if force:
            brand.warn(f"Forcing install despite version mismatch: {error_msg}")
        else:
            brand.error(error_msg, err=True)
            typer.echo(
                "   Pass --force to install anyway (incompatible plugins "
                "may render broken templates).",
                err=True,
            )
            raise typer.Exit(1)

    # Parse bracket-syntax options, e.g. ``scraper[playwright]``.
    parsed_options: dict | None = None
    if is_spec_with_options(spec_str):
        try:
            parsed_options = parse_options(spec_str, plugin_spec)
        except ValueError as e:
            brand.error(f"Invalid options: {e}", err=True)
            raise typer.Exit(1) from e

    # Forward dependency resolution (#776). Walks the plugin's
    # ``required_components`` / ``required_services`` / ``required_plugins``
    # transitively and queues anything missing from the project.
    # Components and services are auto-installed in topological order
    # before the target plugin. Missing pip packages (plugin deps that
    # aren't installed) abort with a clear ``pip install`` instruction
    # — auto-fetching from PyPI would be a network side effect from
    # what's nominally a configure command.
    from ..core.copier_manager import load_copier_answers
    from ..core.plugins.resolver import (
        CircularDependencyError,
        PluginKind,
        UnknownDependencyError,
        format_plan,
        resolve_dependencies,
    )

    try:
        existing_answers = load_copier_answers(target_path)
    except FileNotFoundError as e:
        brand.error(str(e), err=True)
        raise typer.Exit(1) from e

    try:
        plan = resolve_dependencies(plugin_spec, existing_answers)
    except CircularDependencyError as e:
        brand.error(f"Circular plugin dependency: {e}", err=True)
        raise typer.Exit(1) from e
    except UnknownDependencyError as e:
        brand.error(str(e), err=True)
        raise typer.Exit(1) from e

    if plan.unresolved_plugins:
        brand.error(
            f"\n{plugin_spec.name!r} requires plugin packages that aren't installed:",
            err=True,
        )
        for missing in plan.unresolved_plugins:
            typer.echo(f"   pip install {dist_name(missing)}", err=True)
        typer.echo(
            "\n   Install them and re-run ``aegis add``.",
            err=True,
        )
        raise typer.Exit(1)

    # Single confirmation gate. Show the dep plan (if any) + the target
    # plugin's identity, then ask once. Declining leaves the project
    # untouched; accepting commits to installing deps + target as one
    # atomic action. Earlier versions split this into two prompts and
    # installed deps between them — declining the second prompt left
    # the project in a partial state.
    if plan.to_install:
        typer.echo("\n" + format_plan(plan, plugin_spec.name))

    typer.echo(f"\n{t('add.plugin_installing', name=plugin_spec.name)}")
    typer.echo(f"   Description: {plugin_spec.description}")
    typer.echo(f"   Version: {plugin_spec.version}")
    typer.echo(f"   Verified: {plugin_spec.verified}")
    if parsed_options:
        typer.echo(f"   Options: {parsed_options}")

    if not yes and not typer.confirm(
        t("add.plugin_confirm", name=plugin_spec.name), default=True
    ):
        brand.error(t("shared.operation_cancelled"))
        raise typer.Exit(0)

    # Apply the plan in topological order. In-tree components share
    # ``ManualUpdater.add_component``; in-tree services use
    # ``add_service`` so their migrations get bootstrapped and run
    # (just routing through ``add_component`` would land the answer
    # flag but leave the service's tables uncreated). Plugin deps
    # recurse into ``_install_plugin`` so their own deps are resolved
    # and their own ``add_plugin`` lifecycle runs. Every dep install
    # passes ``run_post_gen=False`` — we batch the ``uv sync`` /
    # ``make fix`` pass to a single invocation at the very end so
    # adding a plugin with N transitive deps doesn't trigger N+1
    # syncs. Recursive calls pass ``yes=True`` because the user
    # already confirmed the full plan.
    for dep in plan.to_install:
        typer.echo(f"\n→ Installing dependency: {dep.name}")
        if dep.kind == PluginKind.COMPONENT:
            dep_updater = ManualUpdater(target_path)
            dep_result = dep_updater.add_component(dep.name, None, run_post_gen=False)
        elif dep.name in SERVICES:
            dep_updater = ManualUpdater(target_path)
            dep_result = dep_updater.add_service(dep.name, None, run_post_gen=False)
        else:
            _install_plugin(
                dep.name, target_path, yes=True, force=force, run_post_gen=False
            )
            continue

        if not dep_result.success:
            brand.error(
                f"Dependency {dep.name!r} failed to install: "
                f"{dep_result.error_message}",
                err=True,
            )
            raise typer.Exit(1)

    updater = ManualUpdater(target_path)
    result = updater.add_plugin(
        spec=plugin_spec,
        plugin_module_name=plugin_module_name,
        plugin_options=parsed_options,
        run_post_gen=False,
    )

    if not result.success:
        brand.error(f"\nPlugin install failed: {result.error_message}", err=True)
        raise typer.Exit(1)

    # One sync + format pass for the entire dependency tree. Recursive
    # ``_install_plugin`` invocations forwarded ``run_post_gen=False``;
    # the outermost (top-level CLI) call hits this branch with
    # ``run_post_gen=True`` and amortises the post-gen cost across all
    # the deps + the target plugin.
    if run_post_gen:
        updater.run_post_generation_tasks()

    brand.success(f"\n{t('add.plugin_success', name=plugin_spec.name)}")
    typer.echo()
    render_project_map(target_path, highlight=[plugin_spec.name])
    Messages.print_next_steps()


def _translated_desc(name: str, fallback: str) -> str:
    """Get translated description for a component, with fallback."""
    key = f"component.{name}"
    result = t(key)
    return result if result != key else fallback


def add_command(
    components: str | None = typer.Argument(
        None,
        help=lazy_t("add.help_arg_components"),
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help=lazy_t("common.help_interactive_components"),
    ),
    backend: str | None = typer.Option(
        None,
        "--backend",
        "-b",
        help=lazy_t("add.help_opt_scheduler_backend"),
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
    Add components to an existing Aegis Stack project.

    This command uses Copier's update mechanism to add new components
    to a project that was generated with 'aegis init'.

    Examples:

        - aegis add scheduler

        - aegis add worker,database

        - aegis add scheduler --project-path ../my-project

        - aegis --verbose add worker (show detailed file operations)

    Note: This command only works with projects generated using Copier
    (the default since v0.2.0).

    Global options: Use --verbose/-v before the command for detailed output.
    """

    typer.echo(t("add.title"))
    typer.echo("=" * 50)

    # Resolve project path
    target_path = Path(project_path).resolve()

    # Validate it's a Copier project
    validate_copier_project(target_path, "add")

    typer.echo(t("add.project", path=target_path))

    # Check version compatibility between CLI and project template
    validate_version_compatibility(target_path, command_name="add", force=force)

    # Validate components argument or interactive mode
    if not interactive and not components:
        brand.error(t("add.error_no_args"), err=True)
        typer.echo(f"   {t('add.usage_hint')}", err=True)
        typer.echo(f"   {t('add.interactive_hint')}", err=True)
        raise typer.Exit(1)

    # Plugin / service dispatch — single-name args only. Plugins use
    # bracket syntax which doesn't compose with comma-separated lists;
    # services route through the existing add-service implementation
    # (Phase 2 of #771: unify the entry point, defer the
    # implementation-merge).
    if components and "," not in components:
        if _resolve_plugin(components) is not None:
            validate_git_repository(target_path)
            _install_plugin(components, target_path, yes, force=force)
            return

        # Use the bracket-tolerant helper here too — service bracket
        # syntax (e.g. ``ai[langchain,openai]``) contains commas that
        # ``extract_base_component_name`` rejects.
        service_base = _strip_brackets(components)
        if service_base in SERVICES:
            from .add_service import add_service_command

            add_service_command(
                services=components,
                interactive=False,
                project_path=str(target_path),
                yes=yes,
            )
            return

    # Interactive mode
    if interactive:
        if components:
            brand.warn(t("shared.interactive_ignores_args"))

        from ..cli.interactive import interactive_component_add_selection

        selected_components, scheduler_backend = interactive_component_add_selection(
            target_path
        )

        if not selected_components:
            brand.success(f"\n{t('shared.no_components_selected')}")
            raise typer.Exit(0)

        # Convert to comma-separated string for existing logic
        components = ",".join(selected_components)

        # Auto-confirm in interactive mode
        yes = True

    # Verify project is in a git repository (required for Copier updates)
    validate_git_repository(target_path)

    # Parse and validate components
    assert components is not None  # Already validated by check above
    selected_components = parse_comma_separated_list(components, "component")
    components_raw = selected_components  # Keep for bracket syntax parsing

    # Parse bracket syntax for the scheduler backend (e.g. "scheduler[sqlite]")
    # and the worker backend (e.g. "worker[dramatiq]"). Bracket syntax takes
    # precedence over the --backend flag.
    worker_backend: str | None = None
    for comp in components_raw:
        try:
            base_name = extract_base_component_name(comp)
            if base_name == ComponentNames.SCHEDULER:
                engine = extract_engine_info(comp)
                if engine:
                    if backend and backend != engine:
                        brand.warn(
                            t("add.bracket_override", engine=engine, backend=backend)
                        )
                    backend = engine
            elif base_name == ComponentNames.WORKER:
                engine = extract_engine_info(comp)
                if engine:
                    worker_backend = engine
        except ValueError as e:
            brand.error(t("add.invalid_format", error=e), err=True)
            raise typer.Exit(1)

    # Extract base component names for validation (removes bracket syntax)
    base_components = []
    for comp in selected_components:
        try:
            base_name = extract_base_component_name(comp)
            base_components.append(base_name)
        except ValueError as e:
            brand.error(t("add.invalid_format", error=e), err=True)
            raise typer.Exit(1)

    # Validate components exist and resolve dependencies
    try:
        # Validate component names and resolve dependencies
        errors = DependencyResolver.validate_components(base_components)
        if errors:
            for error in errors:
                brand.error(f"{error}", err=True)
            raise typer.Exit(1)

        # Resolve dependencies
        resolved_components = DependencyResolver.resolve_dependencies(base_components)

        # Show dependency resolution
        auto_added = DependencyResolver.get_missing_dependencies(base_components)
        if auto_added:
            typer.echo(t("add.auto_added_deps", deps=", ".join(auto_added)))

    except typer.Exit:
        raise
    except Exception as e:
        brand.error(t("add.validation_failed", error=e), err=True)
        raise typer.Exit(1)

    # Load existing project configuration
    try:
        existing_answers = load_copier_answers(target_path)
    except Exception as e:
        brand.error(t("add.load_config_failed", error=e), err=True)
        raise typer.Exit(1)

    # Check which components are already enabled
    already_enabled = []
    for component in resolved_components:
        # Check if component is already enabled in answers
        include_key = AnswerKeys.include_key(component)
        if existing_answers.get(include_key) is True:
            already_enabled.append(component)

    if already_enabled:
        typer.echo(t("add.already_enabled", components=", ".join(already_enabled)))

    # Filter out already enabled and core components
    components_to_add = [
        c
        for c in resolved_components
        if c not in already_enabled and c not in CORE_COMPONENTS
    ]

    if not components_to_add:
        brand.success(t("add.all_enabled"))
        raise typer.Exit(0)

    # Detect scheduler backend if adding scheduler
    scheduler_backend = StorageBackends.MEMORY
    if ComponentNames.SCHEDULER in components_to_add:
        # Use explicit backend flag/bracket syntax if provided, otherwise detect
        scheduler_backend = backend or detect_scheduler_backend(components_to_add)

        # Validate backend (memory, sqlite, postgres)
        valid_backends = [
            StorageBackends.MEMORY,
            StorageBackends.SQLITE,
            StorageBackends.POSTGRES,
        ]
        if scheduler_backend not in valid_backends:
            brand.error(
                t("add.invalid_scheduler_backend", backend=scheduler_backend), err=True
            )
            typer.echo(
                f"   {t('add.valid_backends', options=', '.join(valid_backends))}",
                err=True,
            )
            raise typer.Exit(1)

        # A persistent scheduler must match the project's database engine. If
        # a database already exists with a different engine, the schema'd
        # migration (postgres) or create_all (sqlite) won't line up — fail
        # loudly rather than generate a broken stack.
        existing_db_engine = existing_answers.get(AnswerKeys.DATABASE_ENGINE)
        db_already_enabled = (
            existing_answers.get(AnswerKeys.include_key(ComponentNames.DATABASE))
            is True
        )
        if (
            scheduler_backend in (StorageBackends.SQLITE, StorageBackends.POSTGRES)
            and db_already_enabled
            and existing_db_engine
            and existing_db_engine != scheduler_backend
        ):
            brand.error(
                t(
                    "add.scheduler_db_engine_mismatch",
                    backend=scheduler_backend,
                    engine=existing_db_engine,
                ),
                err=True,
            )
            raise typer.Exit(1)

        # Persistent backends need a database component; auto-add one (with a
        # matching engine) if the project doesn't have it yet.
        if (
            scheduler_backend in (StorageBackends.SQLITE, StorageBackends.POSTGRES)
            and not db_already_enabled
            and ComponentNames.DATABASE not in components_to_add
        ):
            components_to_add.append(ComponentNames.DATABASE)
            typer.echo(t("add.auto_added_db"))

    # Show what will be added
    typer.echo(f"\n{t('add.components_to_add')}")
    for component in components_to_add:
        if component in COMPONENTS:
            desc = _translated_desc(component, COMPONENTS[component].description)
            typer.echo(f"   • {component}: {desc}")

    if (
        ComponentNames.SCHEDULER in components_to_add
        and scheduler_backend != StorageBackends.MEMORY
    ):
        typer.echo(f"\n{t('add.scheduler_backend', backend=scheduler_backend)}")

    # Confirm before proceeding
    typer.echo()
    if not yes and not typer.confirm(t("add.confirm"), default=True):
        brand.error(t("shared.operation_cancelled"))
        raise typer.Exit(0)

    # Prepare update data for Copier
    update_data: dict[str, bool | str] = {}

    for component in components_to_add:
        include_key = AnswerKeys.include_key(component)
        update_data[include_key] = True

    # Add scheduler backend configuration if adding scheduler
    if ComponentNames.SCHEDULER in components_to_add:
        update_data[AnswerKeys.SCHEDULER_BACKEND] = scheduler_backend
        update_data[AnswerKeys.SCHEDULER_WITH_PERSISTENCE] = (
            scheduler_backend == StorageBackends.SQLITE
        )

    # Add database engine configuration if adding database. Match the
    # scheduler backend when adding the DB for a persistent scheduler;
    # default to SQLite otherwise.
    if ComponentNames.DATABASE in components_to_add:
        update_data[AnswerKeys.DATABASE_ENGINE] = (
            StorageBackends.POSTGRES
            if scheduler_backend == StorageBackends.POSTGRES
            else StorageBackends.SQLITE
        )

    # Add worker backend configuration when adding worker with a bracket backend
    # (e.g. "worker[dramatiq]"); without this the add path falls back to the
    # copier default (arq) and silently ignores the chosen backend.
    if ComponentNames.WORKER in components_to_add and worker_backend:
        if worker_backend not in WorkerBackends.ALL:
            brand.error(
                t("add.invalid_worker_backend", backend=worker_backend), err=True
            )
            raise typer.Exit(1)
        update_data[AnswerKeys.WORKER_BACKEND] = worker_backend

    # Add components using ManualUpdater
    # This is the standard approach for adding components at the same template version
    # (Copier's run_update is designed for template VERSION upgrades, not component additions)
    try:
        updater = ManualUpdater(target_path)

        # Add each component sequentially
        for component in components_to_add:
            typer.echo(f"\n{t('add.adding', component=component)}")

            # Prepare component-specific data
            component_data: dict[str, bool | str] = {}
            if (
                component == ComponentNames.SCHEDULER
                and AnswerKeys.SCHEDULER_BACKEND in update_data
            ):
                component_data[AnswerKeys.SCHEDULER_BACKEND] = update_data[
                    AnswerKeys.SCHEDULER_BACKEND
                ]
                component_data[AnswerKeys.SCHEDULER_WITH_PERSISTENCE] = update_data.get(
                    AnswerKeys.SCHEDULER_WITH_PERSISTENCE, False
                )
            elif (
                component == ComponentNames.DATABASE
                and AnswerKeys.DATABASE_ENGINE in update_data
            ):
                component_data[AnswerKeys.DATABASE_ENGINE] = update_data[
                    AnswerKeys.DATABASE_ENGINE
                ]
            elif (
                component == ComponentNames.WORKER
                and AnswerKeys.WORKER_BACKEND in update_data
            ):
                component_data[AnswerKeys.WORKER_BACKEND] = update_data[
                    AnswerKeys.WORKER_BACKEND
                ]

            # Add the component
            result = updater.add_component(component, component_data)

            if not result.success:
                brand.error(
                    t(
                        "add.failed_component",
                        component=component,
                        error=result.error_message,
                    ),
                    err=True,
                )
                raise typer.Exit(1)

            # Show results
            if result.files_modified:
                brand.success(
                    f"   {t('add.added_files', count=len(result.files_modified))}"
                )
            if result.files_skipped:
                brand.warn(
                    f"   {t('add.skipped_files', count=len(result.files_skipped))}"
                )

        # Generate migrations for newly-added components that own tables.
        # Today that's scheduler[postgres] -> scheduler.job_execution; the
        # schema'd migration runs at backend startup on Postgres. SQLite
        # scheduler creates its table via create_all, so it needs no file.
        if (
            ComponentNames.SCHEDULER in components_to_add
            and scheduler_backend == StorageBackends.POSTGRES
        ):
            from ..core.migration_generator import (
                bootstrap_alembic,
                generate_migration,
                service_has_migration,
            )

            if not (target_path / "alembic").exists():
                bootstrap_alembic(target_path, updater.jinja_env, updater.answers)
            if not service_has_migration(target_path, ComponentNames.SCHEDULER):
                migration_path = generate_migration(
                    target_path, ComponentNames.SCHEDULER
                )
                if migration_path:
                    brand.success(
                        f"   {t('add.generated_migration', name=migration_path.name)}"
                    )

        brand.success(f"\n{t('add.success')}")

        # Show project map with newly added components highlighted
        typer.echo()
        render_project_map(target_path, highlight=components_to_add)

        # Note: Shared file updates are already shown during the update process
        # Just provide next steps

        if len(components_to_add) > 0:
            Messages.print_review_changes()

        Messages.print_next_steps()

    except Exception as e:
        brand.error(f"\n{t('add.failed', error=e)}", err=True)
        raise typer.Exit(1)
