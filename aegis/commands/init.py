"""
Init command implementation.
"""

from pathlib import Path
from typing import cast

import typer

from ..blueprints import BLUEPRINTS, Blueprint, blueprint_selection, get_blueprint
from ..cli import brand
from ..cli.build_plan import BuildPlan, resolve_build_plan
from ..cli.callbacks import (
    apply_service_option_handlers,
    validate_and_resolve_components,
    validate_and_resolve_services,
)
from ..cli.guided import GuidedBuildError, run_guided_init_flow
from ..cli.interactive import (
    get_skip_llm_sync_selection,
    interactive_project_selection,
)
from ..cli.utils import detect_scheduler_backend
from ..cli.validators import validate_project_name
from ..config.defaults import DEFAULT_PYTHON_VERSION, SUPPORTED_PYTHON_VERSIONS
from ..constants import StorageBackends
from ..core.ai_service_parser import BACKENDS, FRAMEWORKS, PROVIDERS
from ..core.component_utils import (
    extract_base_component_name,
)
from ..core.components import (
    COMPONENTS,
    CORE_COMPONENTS,
    ComponentType,
)
from ..core.service_resolver import ServiceResolver
from ..core.services import SERVICES
from ..core.template_generator import TemplateGenerator
from ..i18n import lazy_t, t

# Build services help text dynamically from constants
_SERVICES_HELP = lazy_t(
    "init.help_opt_services",
    services=", ".join(sorted(SERVICES)),
    frameworks="|".join(sorted(FRAMEWORKS)),
    backends="|".join(sorted(BACKENDS)),
    providers="|".join(sorted(PROVIDERS)),
)


def build_replay_command(
    project_name: str,
    components: list[str],
    services: list[str],
) -> str:
    """The uvx one-liner that reproduces this exact stack non-interactively.

    Selections carry their bracket syntax (``scheduler[sqlite]``,
    ``auth[rbac]``, ``ai[memory,pydantic-ai,public,rag]``), so feeding them
    back through ``--components``/``--services`` re-resolves to the same
    project. CORE components ship in every project and are dropped.
    """
    parts = [f"uvx aegis-stack init {project_name}"]
    # Defensive base-name dedupe: prefer the bracketed variant when both a
    # plain and a configured form of the same component slipped through.
    by_base: dict[str, str] = {}
    order: list[str] = []
    for comp in components:
        base = comp.split("[", 1)[0]
        if base in CORE_COMPONENTS:
            continue
        if base not in by_base:
            by_base[base] = comp
            order.append(base)
        elif "[" in comp and "[" not in by_base[base]:
            by_base[base] = comp
    non_core = [by_base[base] for base in order]
    # Quoted: bracket syntax is a glob pattern to zsh (and friends), so an
    # unquoted database[postgres] makes the shell error before uvx runs.
    if non_core:
        parts.append(f'--components "{",".join(non_core)}"')
    if services:
        parts.append(f'--services "{",".join(services)}"')
    parts.append("--no-interactive")
    return " ".join(parts)


def _remove_existing_project(project_path: Path) -> None:
    """Remove an existing project dir, tolerating git background races."""
    import errno
    import shutil

    typer.echo(t("init.removing_dir", path=project_path))

    def _ignore_vanished(_func: object, path: str, exc_info: object) -> None:
        # Two symmetric races against background git activity
        # (pack-refs, gc, fsmonitor) on a ``.git`` we just created:
        #
        # 1. A file is enumerated then unlinked by git before we
        #    can ``unlink`` it ourselves. Manifests as
        #    ``FileNotFoundError`` — safe to ignore, the walk has
        #    already done the work.
        # 2. New files appear inside a directory between our walk
        #    and the final ``rmdir`` of that directory, leaving it
        #    non-empty. Manifests as ``OSError`` with
        #    ``errno.ENOTEMPTY``. Re-rmtree the offending subdir;
        #    its fresh contents will get cleaned up. The recursion
        #    is bounded by how many times git can race us, which
        #    in practice is once.
        exc = exc_info[1] if isinstance(exc_info, tuple) else None
        if isinstance(exc, FileNotFoundError):
            return
        if isinstance(exc, OSError) and exc.errno == errno.ENOTEMPTY:
            shutil.rmtree(path, onerror=_ignore_vanished)
            return
        raise exc  # type: ignore[misc]

    shutil.rmtree(project_path, onerror=_ignore_vanished)


def _print_guided_receipt(plan: BuildPlan, project_path: Path) -> None:
    """Persistent scrollback summary after the guided experience closes.

    The full journey lived in the (ephemeral) alternate screen; this is
    the part worth keeping: what was built, how to run it, how to rebuild
    it. Reuses the post-gen i18n strings so quick and guided stay in step.
    """
    from rich.console import Console
    from rich.text import Text

    from ..cli.brand import AEGIS_TEAL

    typer.echo()
    brand.success(t("postgen.ready"), bold=True)
    typer.echo(t("postgen.next_cd", path=project_path))
    typer.echo(t("postgen.next_serve"))
    typer.echo(t("postgen.next_dashboard"))
    typer.echo()
    brand.muted(t("init.replay_hint"))
    replay = build_replay_command(plan.project_name, plan.components, plan.services)
    # soft_wrap: emit one logical line. Rich would otherwise hard-wrap to
    # the terminal width with REAL newlines, breaking copy-paste of the
    # command; soft-wrapped output copies clean even when it displays
    # across multiple rows.
    Console(highlight=False).print(
        Text(f"   {replay}", style=AEGIS_TEAL), soft_wrap=True
    )


def _show_config_and_confirm(
    project_name: str,
    selected_components: list[str],
    selected_services: list[str],
    template_gen: TemplateGenerator,
    yes: bool,
) -> None:
    """Quick-mode preview: the terminal config dump plus the [Y/n] confirm.

    The guided flow renders the same information as its REVIEW screen and
    skips this entirely.
    """
    typer.echo()
    brand.muted(t("init.config_title"), bold=True)
    typer.echo(f"   {brand.muted_text(t('init.config_name'))} {project_name}")
    typer.echo(
        f"   {brand.muted_text(t('init.config_core'))} {', '.join(CORE_COMPONENTS)}"
    )

    # Show selected components, grouped by type so the labels stay true:
    # an optional frontend is not infrastructure.
    def _selected_of_type(component_type: ComponentType) -> list[str]:
        out = []
        for name in selected_components:
            # Handle database[engine] format
            base_name = extract_base_component_name(name)
            if base_name in COMPONENTS and COMPONENTS[base_name].type == component_type:
                out.append(name)
        return out

    for label_key, group in (
        ("init.config_infra", _selected_of_type(ComponentType.INFRASTRUCTURE)),
        ("init.config_web_frontend", _selected_of_type(ComponentType.FRONTEND)),
    ):
        if group:
            typer.echo(f"   {brand.muted_text(t(label_key))} {', '.join(group)}")

    # Show selected services
    if selected_services:
        typer.echo(
            f"   {brand.muted_text(t('init.config_services'))} {', '.join(selected_services)}"
        )

    # Show template files that will be generated
    template_files = template_gen.get_template_files()
    if template_files:
        brand.muted("\n" + t("init.component_files"), bold=True)
        for file_path in template_files:
            typer.echo(f"   • {file_path}")

    # Show entrypoints that will be created
    entrypoints = template_gen.get_entrypoints()
    if entrypoints:
        brand.muted("\n" + t("init.entrypoints"), bold=True)
        for entrypoint in entrypoints:
            typer.echo(f"   • {entrypoint}")

    # Show worker queues that will be created
    worker_queues = template_gen.get_worker_queues()
    if worker_queues:
        brand.muted("\n" + t("init.worker_queues"), bold=True)
        for queue in worker_queues:
            typer.echo(f"   • {queue}")

    # Show dependency information using template generator
    deps = template_gen._get_pyproject_deps()
    if deps:
        brand.muted("\n" + t("init.dependencies"), bold=True)
        for dep in deps:
            typer.echo(f"   • {dep}")

    # Confirm before proceeding
    typer.echo()
    if not yes and not typer.confirm(t("init.confirm_create"), default=True):
        brand.error(t("init.cancelled"))
        raise typer.Exit(0)


def init_command(
    project_name: str = typer.Argument(..., help=lazy_t("init.help_arg_name")),
    components: str | None = typer.Option(
        None,
        "--components",
        "-c",
        callback=validate_and_resolve_components,
        help=lazy_t("init.help_opt_components"),
    ),
    services: str | None = typer.Option(
        None,
        "--services",
        "-s",
        callback=validate_and_resolve_services,
        help=_SERVICES_HELP,
    ),
    blueprint: str | None = typer.Option(
        None,
        "--blueprint",
        "-b",
        help=lazy_t("init.help_opt_blueprint"),
    ),
    python_version: str = typer.Option(
        DEFAULT_PYTHON_VERSION,
        "--python-version",
        help=lazy_t("init.help_opt_python"),
    ),
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        "-i/-ni",
        help=lazy_t("common.help_interactive_components"),
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help=lazy_t("init.help_opt_force")
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help=lazy_t("init.help_opt_directory"),
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help=lazy_t("common.help_yes")),
    to_version: str | None = typer.Option(
        None,
        "--to-version",
        help=lazy_t("init.help_opt_template_version"),
    ),
    skip_llm_sync: bool = typer.Option(
        False,
        "--skip-llm-sync",
        help=lazy_t("init.help_opt_no_llm_sync"),
    ),
    dev: bool = typer.Option(
        False,
        "--dev",
        help=lazy_t("init.help_opt_dev"),
    ),
    guided: bool = typer.Option(
        True,
        "--guided/--quick",
        help=(
            "Full-screen guided setup (the default). --quick uses the "
            "classic one-line prompts instead."
        ),
    ),
) -> None:
    """
    Initialize a new Aegis Stack project with battle-tested component combinations.

    This command creates a complete project structure with your chosen components,
    ensuring all dependencies and configurations are compatible and tested.

    Examples:\\n
        - aegis init my-app\\n
        - aegis init my-app --components redis,worker\\n
        - aegis init my-app --components redis,worker,scheduler,database --no-interactive\\n
        - aegis init my-app --services auth --no-interactive\\n
    """  # noqa

    # Validate project name first
    validate_project_name(project_name)

    # Validate Python version
    if python_version not in SUPPORTED_PYTHON_VERSIONS:
        brand.error(
            t(
                "validation.invalid_python",
                version=python_version,
                supported=", ".join(SUPPORTED_PYTHON_VERSIONS),
            ),
            err=True,
        )
        raise typer.Exit(1)

    brand.accent(t("init.title"), bold=True)

    # Determine output directory
    base_output_dir = Path(output_dir) if output_dir else Path.cwd()
    project_path = base_output_dir / project_name

    typer.echo(f"{brand.muted_text(t('init.location'))} {project_path.resolve()}")

    if to_version:
        typer.echo(f"{brand.muted_text(t('init.template_version'))} {to_version}")

    # Check if directory already exists
    if project_path.exists():
        if not force:
            brand.error(t("init.dir_exists", path=project_path), err=True)
            typer.echo(f"   {t('init.dir_exists_hint')}", err=True)
            raise typer.Exit(1)
        else:
            brand.warn(t("init.overwriting", path=project_path))

    # Blueprint expansion: run the selection engine headlessly with the
    # blueprint answering, then treat the result exactly like explicit
    # --components/--services (which win where given). Service bracket
    # options flow through the same handlers as typed flags.
    # Interactive component selection
    # Note: components is list[str] after callback, despite str annotation
    selected_components = cast(list[str], components) if components else []
    selected_services = cast(list[str], services) if services else []
    components_given = components is not None
    services_given = services is not None

    preset: Blueprint | None = None
    if blueprint is not None:
        preset = get_blueprint(blueprint)
        if preset is None:
            brand.error(
                t(
                    "init.unknown_blueprint",
                    name=blueprint,
                    available=", ".join(sorted(BLUEPRINTS)),
                ),
                err=True,
            )
            raise typer.Exit(1)
        # Interactive (the default) hands the preset to the guided flow so
        # the plan is reviewed on screen before building. --no-interactive
        # expands it headlessly here, as does mixing it with explicit
        # --components/--services (those win, and the guided flow only runs
        # when neither was given). The expansion fills the resolved lists
        # directly - the raw option params keep their real (str | None)
        # type and are never reassigned.
        if not interactive or components_given or services_given:
            selection = blueprint_selection(preset)
            if not components_given:
                selected_components = selection.components
                components_given = True
            if not services_given:
                selected_services = selection.services
                services_given = True
                apply_service_option_handlers(selection.services)
    scheduler_backend = StorageBackends.MEMORY  # Default to in-memory scheduler

    # Resolve services to components if services were provided
    # This runs in both interactive and non-interactive modes when --services is specified
    if selected_services:
        # Check if --components was explicitly provided
        components_explicitly_provided = components_given

        if components_explicitly_provided:
            # In non-interactive mode with explicit --components, validate compatibility
            # Include core components (always present) for validation
            components_for_validation = list(set(selected_components + CORE_COMPONENTS))
            errors = ServiceResolver.validate_service_component_compatibility(
                selected_services, components_for_validation
            )
            if errors:
                brand.error(t("init.compat_errors"), err=True)
                for error in errors:
                    typer.echo(f"   • {error}", err=True)

                # Show suggestion
                missing_components = (
                    ServiceResolver.get_missing_components_for_services(
                        selected_services, components_for_validation
                    )
                )
                if missing_components:
                    typer.echo(
                        t(
                            "init.suggestion_add",
                            components=",".join(
                                sorted(set(selected_components + missing_components))
                            ),
                        ),
                        err=True,
                    )
                    typer.echo(
                        f"   {t('init.suggestion_remove')}",
                        err=True,
                    )
                typer.echo(
                    f"   {t('init.suggestion_interactive')}",
                    err=True,
                )
                raise typer.Exit(1)
        else:
            # No --components provided, auto-add required components for services
            service_components, _ = ServiceResolver.resolve_service_dependencies(
                selected_services
            )
            if service_components:
                brand.warn(
                    t(
                        "init.services_require",
                        components=", ".join(sorted(service_components)),
                    )
                )
            selected_components = service_components

        # Resolve service dependencies and merge with any explicitly selected components
        service_components, _ = ServiceResolver.resolve_service_dependencies(
            selected_services
        )
        # Merge service-required components with explicitly selected components
        all_components = list(set(selected_components + service_components))
        selected_components = all_components

    # Auto-detect scheduler backend when components are specified
    if selected_components:
        scheduler_backend = detect_scheduler_backend(selected_components)
        if scheduler_backend != StorageBackends.MEMORY:
            brand.warn(t("init.auto_detected_scheduler", backend=scheduler_backend))

    if interactive and not components_given and not services_given:
        import shutil as _shutil
        import sys as _sys

        from ..cli.guided import MIN_HEIGHT, MIN_WIDTH

        # Guided is the default but needs a real, big-enough terminal
        # (raw keys + alternate screen). Anything else — CI, piped stdin,
        # tiny terminals — quietly falls back to the quick prompts.
        term = _shutil.get_terminal_size()
        use_guided = (
            guided
            and _sys.stdin.isatty()
            and _sys.stdout.isatty()
            and term.columns >= MIN_WIDTH
            and term.lines >= MIN_HEIGHT
        )
        if use_guided:
            # The full-screen experience end to end: welcome, questions,
            # REVIEW (replacing the config dump + [Y/n]), the build itself
            # (output captured; a building screen holds the frame), and the
            # DONE card. Same engine, same resolution, same generation —
            # only the rendering differs. A compact receipt persists in
            # normal scrollback afterwards.
            project_path = base_output_dir / project_name

            from ..core.build_reporter import BuildReporter

            def _guided_builder(plan: "BuildPlan", reporter: BuildReporter) -> Path:
                if force and project_path.exists():
                    _remove_existing_project(project_path)
                from ..core.copier_manager import generate_with_copier

                assert plan.template_gen is not None
                generate_with_copier(
                    plan.template_gen,
                    base_output_dir,
                    vcs_ref=to_version,
                    skip_llm_sync=skip_llm_sync or get_skip_llm_sync_selection(),
                    dev_mode=dev,
                    reporter=reporter,
                )
                return project_path

            try:
                plan, _ = run_guided_init_flow(
                    project_name,
                    python_version,
                    yes=yes,
                    blueprint=preset,
                    builder=_guided_builder,
                    replay_command=lambda p: build_replay_command(
                        p.project_name, p.components, p.services
                    ),
                )
            except GuidedBuildError as exc:
                # The screen is gone; put the full captured build log and
                # the error into persistent scrollback.
                if exc.log.strip():
                    typer.echo(exc.log)
                brand.error(t("init.error", error=exc.__cause__), err=True)
                raise typer.Exit(1) from exc

            _print_guided_receipt(plan, project_path)
            return
        else:
            (
                selected_components,
                scheduler_backend,
                interactive_services,
                interactive_skip_llm_sync,
            ) = interactive_project_selection()
            # Use interactive selection if user chose to skip (overrides CLI default)
            if interactive_skip_llm_sync:
                skip_llm_sync = True

            plan = resolve_build_plan(
                project_name,
                selected_components,
                scheduler_backend,
                list(set(selected_services + interactive_services)),
                python_version,
            )
            selected_components = plan.components
            selected_services = plan.services

            if plan.auto_added_components:
                brand.warn(
                    "\n"
                    + t(
                        "init.auto_added_deps",
                        deps=", ".join(plan.auto_added_components),
                    )
                )
            if plan.service_component_map:
                brand.warn("\n" + t("init.auto_added_by_services"))
                for comp, requiring_services in plan.service_component_map.items():
                    services_str = ", ".join(requiring_services)
                    typer.echo(
                        f"   • {comp} {brand.muted_text(t('init.required_by', services=services_str))}"
                    )
        template_gen = plan.template_gen
        assert template_gen is not None
    else:
        # Non-interactive: callbacks already validated and resolved.
        template_gen = TemplateGenerator(
            project_name,
            list(selected_components),
            scheduler_backend,
            selected_services,
            python_version,
        )

    # Show selected configuration and confirm. (The guided flow never
    # reaches here: it reviews, builds, and returns inside its branch.)
    _show_config_and_confirm(
        project_name, selected_components, selected_services, template_gen, yes
    )

    # Handle force overwrite by completely removing existing directory
    project_path = base_output_dir / project_name
    if force and project_path.exists():
        _remove_existing_project(project_path)

    # Create project using Copier template engine
    typer.echo()
    brand.accent(t("init.creating", name=project_name), bold=True)

    try:
        from ..core.copier_manager import generate_with_copier

        generate_with_copier(
            template_gen,
            base_output_dir,
            vcs_ref=to_version,
            skip_llm_sync=skip_llm_sync,
            dev_mode=dev,
        )

        # Note: Comprehensive setup output is now handled by the post-generation hook
        # which provides better status reporting and automated setup

        # Replay hint: the exact command that recreates this stack without
        # the prompts.
        from rich.console import Console

        from ..cli.brand import AEGIS_TEAL

        replay = build_replay_command(
            project_name, list(selected_components), selected_services
        )
        typer.echo()
        brand.muted(t("init.replay_hint"))
        # Text, not markup interpolation: bracket syntax like worker[taskiq]
        # would be parsed (and swallowed) as rich markup tags.
        from rich.text import Text as _RichText

        # soft_wrap: one logical line; see _print_guided_receipt.
        Console(highlight=False).print(
            _RichText(f"   {replay}", style=AEGIS_TEAL), soft_wrap=True
        )

    except Exception as e:
        brand.error(t("init.error", error=e), err=True)
        raise typer.Exit(1)
