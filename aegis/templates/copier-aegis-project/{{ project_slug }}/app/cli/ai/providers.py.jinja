"""Which model answers: listing, adding and choosing a provider."""

from rich.prompt import Prompt
from rich.table import Table
import typer

from app.cli import theme
from app.cli.ai.shared import (
    app,
    console,
    get_provider_display_name,
)
from app.i18n import lazy_t, t

from ...core.config import settings
from ...services.ai.config import get_ai_config
from ...services.ai.models import (
    AIProvider,
    get_free_providers,
    get_provider_capabilities,
)


@app.command(help=lazy_t("ai.help_status"))
def status() -> None:
    ai_config = get_ai_config(settings)

    theme.title(t("ai.status_title"))
    theme.label("=" * 40)

    # Field rows: dim labels, neutral values. Teal marks only state.
    typer.echo(theme.label_text(t("ai.engine_label") + " ") + "pydantic-ai")
    status_value = (
        theme.good_text(t("ai.enabled"))
        if ai_config.enabled
        else theme.bad_text(t("ai.disabled"))
    )
    typer.echo(theme.label_text(t("ai.status_label") + " ") + status_value)
    typer.echo(
        theme.label_text(t("ai.provider_label") + " ")
        + get_provider_display_name(ai_config.provider)
    )
    typer.echo(theme.label_text(t("ai.model_label") + " ") + str(ai_config.model))
    typer.echo(
        theme.label_text(t("ai.temperature_label") + " ") + str(ai_config.temperature)
    )
    typer.echo(
        theme.label_text(t("ai.max_tokens_label") + " ") + str(ai_config.max_tokens)
    )

    # API key: present is a good state (teal); absent is just a fact (neutral),
    # not an error — the validation verdict below carries the real judgment.
    provider_config = ai_config.get_provider_config(settings)
    api_key_value = (
        theme.good_text(t("shared.yes")) if provider_config.api_key else t("shared.no")
    )
    typer.echo(theme.label_text(t("ai.api_key_label") + " ") + api_key_value)

    # Validation — the one verdict the eye is hunting for.
    typer.echo("")
    errors = ai_config.validate_configuration(settings)
    if not errors:
        theme.good(f"✓ {t('ai.config_valid')}")
        capabilities = get_provider_capabilities(ai_config.provider)
        if capabilities.free_tier_available:
            theme.label("  " + t("ai.free_tier"))
        if capabilities.supports_streaming:
            theme.label("  " + t("ai.streaming_supported"))
    else:
        theme.bad(f"✗ {t('ai.config_issues')}")
        for error in errors:
            typer.echo("  " + theme.bad_text("•") + f" {error}")

        # Suggest free providers if API key issues
        if any("API key" in error for error in errors):
            free_providers = get_free_providers()
            if free_providers:
                providers_list = ", ".join(p.value for p in free_providers)
                typer.echo("")
                typer.echo(
                    theme.label_text(t("ai.tip_label") + " ") + f"{providers_list}"
                )

    # Available providers count
    available = ai_config.get_available_providers(settings)
    typer.echo("")
    typer.echo(
        theme.label_text(t("ai.available_providers") + " ") + f"{len(available)}"
    )


@app.command(help=lazy_t("ai.help_providers"))
def providers() -> None:
    from ..services.ai.domains.llm.provider_management import (
        check_provider_dependency_installed,
    )

    ai_config = get_ai_config(settings)
    available = ai_config.get_available_providers(settings)
    free_providers = get_free_providers()

    _yes = f"[{theme.ACCENT}]{t('ai.prov_yes')}[/{theme.ACCENT}]"
    _no = f"[{theme.ERROR}]{t('ai.prov_no')}[/{theme.ERROR}]"
    _no_dim = f"[dim]{t('ai.prov_no')}[/dim]"

    table = Table(title=t("ai.providers_title"), width=115)
    table.add_column(t("ai.col_provider"), style=theme.ACCENT, width=10)
    table.add_column(t("ai.col_installed"), width=9)
    table.add_column(t("ai.col_api_key"), width=8)
    table.add_column(t("ai.col_status"), width=26, no_wrap=True)
    table.add_column(t("ai.col_free"), style="dim", width=4)
    table.add_column(t("ai.col_stream"), width=6, justify="center")
    table.add_column(t("ai.col_functions"), width=9, justify="center")
    table.add_column(t("ai.col_vision"), width=6, justify="center")

    for provider in AIProvider:
        capabilities = get_provider_capabilities(provider)
        is_installed = check_provider_dependency_installed(provider.value)
        is_available = provider in available
        is_current = provider == ai_config.provider

        # Determine API key status
        # LOCAL providers (PUBLIC, OLLAMA) don't require API keys
        local_providers = {AIProvider.PUBLIC, AIProvider.OLLAMA}
        if provider in local_providers:
            has_api_key = True  # Local providers don't need API keys
            api_key_display = f"[dim]{t('ai.prov_na')}[/dim]"
        else:
            env_var = f"{provider.value.upper()}_API_KEY"
            has_api_key = bool(getattr(settings, env_var, None))
            api_key_display = _yes if has_api_key else _no

        # Determine status
        if is_current:
            if not is_installed:
                status = f"[bold {theme.ERROR}]{t('ai.prov_current_not_installed')}[/bold {theme.ERROR}]"
            elif not has_api_key and provider not in local_providers:
                status = f"[bold {theme.WARNING}]{t('ai.prov_current_need_key')}[/bold {theme.WARNING}]"
            elif provider == AIProvider.OLLAMA:
                status = f"[bold {theme.ACCENT}]{t('ai.prov_current_local')}[/bold {theme.ACCENT}]"
            else:
                status = (
                    f"[bold {theme.ACCENT}]{t('ai.prov_current')}[/bold {theme.ACCENT}]"
                )
        elif is_available:
            status = (
                t("ai.prov_ready")
                if provider not in local_providers
                else t("ai.prov_local")
            )
        elif is_installed and not has_api_key:
            status = f"[{theme.WARNING}]{t('ai.prov_need_key')}[/{theme.WARNING}]"
        elif is_installed and provider == AIProvider.OLLAMA:
            status = f"[{theme.ACCENT}]{t('ai.prov_local')}[/{theme.ACCENT}]"
        elif not is_installed:
            status = f"[{theme.ERROR}]{t('ai.prov_not_installed')}[/{theme.ERROR}]"
        else:
            status = f"[{theme.ERROR}]{t('ai.prov_error')}[/{theme.ERROR}]"

        installed_display = _yes if is_installed else _no
        free_tier = t("ai.prov_yes") if provider in free_providers else t("ai.prov_no")

        table.add_row(
            get_provider_display_name(provider),
            installed_display,
            api_key_display,
            status,
            free_tier,
            _yes if capabilities.supports_streaming else _no_dim,
            _yes if capabilities.supports_function_calling else _no_dim,
            _yes if capabilities.supports_vision else _no_dim,
        )

    console.print(table)
    console.print()
    console.print(f"[dim]{t('ai.providers_tip', app='aidb')}[/dim]")


@app.command("add-provider", help=lazy_t("ai.help_add_provider"))
def add_provider(
    provider: str = typer.Argument(
        ...,
        help=lazy_t("ai.arg_provider"),
    ),
    set_default: bool = typer.Option(
        True,
        "--set-default/--no-set-default",
        help=lazy_t("ai.opt_set_default"),
    ),
    skip_api_key: bool = typer.Option(
        False,
        "--skip-api-key",
        help=lazy_t("ai.opt_skip_api_key"),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=lazy_t("ai.opt_yes"),
    ),
) -> None:
    from rich.progress import Progress, SpinnerColumn, TextColumn

    from ..services.ai.domains.llm.provider_management import (
        PROVIDER_API_KEY_URLS,
        get_env_var_name,
        get_existing_api_key,
        get_missing_dependency,
        get_valid_provider_names,
        install_provider_dependency,
        update_env_file,
        validate_provider_name,
    )

    # Validate provider name
    provider_enum = validate_provider_name(provider)
    if not provider_enum:
        valid_names = ", ".join(get_valid_provider_names())
        console.print(
            f"[{theme.ERROR}]{t('ai.invalid_provider', provider=provider)}[/{theme.ERROR}]"
        )
        console.print(f"[dim]{t('ai.valid_providers', names=valid_names)}[/dim]")
        raise typer.Exit(1)

    console.print()
    console.print(f"[bold]{t('ai.adding_provider', provider=provider)}[/bold]")
    console.print()

    # Check if dependency is installed
    missing_dep = get_missing_dependency(provider)
    if missing_dep:
        console.print(f"  [dim]>[/dim] {t('ai.checking_deps')}")
        # Escape brackets for Rich (otherwise [google] is interpreted as style)
        display_dep = missing_dep.replace("[", r"\[")
        console.print(f"    [{theme.WARNING}]{display_dep}[/{theme.WARNING}]")
        console.print()

        # Prompt for installation unless --yes
        if not yes:
            confirm = typer.confirm(t("ai.install_dep", dep=missing_dep), default=True)
            if not confirm:
                console.print(
                    f"[{theme.WARNING}]{t('ai.install_cancelled')}[/{theme.WARNING}]"
                )
                raise typer.Exit(0)

        # Install with progress spinner
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            progress.add_task(description=t("ai.installing"), total=None)
            success, message = install_provider_dependency(provider)

        if success:
            console.print(f"  [{theme.ACCENT}]✓[/{theme.ACCENT}] {message}")
        else:
            console.print(f"  [{theme.ERROR}]✗[/{theme.ERROR}] {message}")
            console.print()
            console.print(
                f"[{theme.WARNING}]{t('ai.install_failed_hint')}[/{theme.WARNING}]"
            )
            console.print(f"  [{theme.ACCENT}]uv add {missing_dep}[/{theme.ACCENT}]")
            console.print("  [dim]or[/dim]")
            console.print(
                f"  [{theme.ACCENT}]pip install {missing_dep}[/{theme.ACCENT}]"
            )
            raise typer.Exit(1)
    else:
        console.print(f"  [{theme.ACCENT}]✓[/{theme.ACCENT}] {t('ai.deps_installed')}")

    # Handle API key configuration
    if provider_enum != AIProvider.PUBLIC and not skip_api_key:
        env_var_name = get_env_var_name(provider)
        existing_key = get_existing_api_key(provider)

        console.print()
        if existing_key:
            console.print(f"  [{theme.ACCENT}]✓[/{theme.ACCENT}] {env_var_name}")
        else:
            api_key_url = PROVIDER_API_KEY_URLS.get(provider.lower())
            console.print(f"  [dim]>[/dim] {t('ai.checking_api_key')}")
            console.print(
                f"    [{theme.WARNING}]{t('ai.no_api_key', var=env_var_name)}[/{theme.WARNING}]"
            )
            console.print()

            if api_key_url:
                console.print(
                    f"  {t('ai.get_api_key_at')} [{theme.ACCENT}]{api_key_url}[/{theme.ACCENT}]"
                )
                console.print()

            # Prompt for API key
            try:
                api_key = Prompt.ask(
                    f"  {t('ai.enter_api_key', provider=provider.upper())}",
                    console=console,
                    password=True,
                    default="",
                )
            except (KeyboardInterrupt, EOFError):
                console.print(
                    f"\n[{theme.WARNING}]{t('ai.api_key_skipped')}[/{theme.WARNING}]"
                )
                api_key = ""

            if api_key:
                update_env_file({env_var_name: api_key})
                console.print(
                    f"  [{theme.ACCENT}]✓[/{theme.ACCENT}] {env_var_name} → .env"
                )
            else:
                console.print(
                    f"  [{theme.WARNING}]![/{theme.WARNING}] {env_var_name} → .env"
                )

    # Set as default provider
    if set_default:
        update_env_file({"AI_PROVIDER": provider.lower()})
        console.print()
        console.print(
            f"  [{theme.ACCENT}]✓[/{theme.ACCENT}] {t('ai.provider_set', provider=provider)}"
        )

    # Success message
    console.print()
    console.print(
        f"[bold {theme.ACCENT}]{t('ai.provider_added')}[/bold {theme.ACCENT}]"
    )
    console.print()
    console.print(f"[dim]{t('ai.test_with', app='aidb')}[/dim]")


@app.command("use-provider", help=lazy_t("ai.help_use_provider"))
def use_provider(
    provider: str = typer.Argument(
        ...,
        help=lazy_t("ai.arg_provider_switch"),
    ),
) -> None:
    from ..services.ai.domains.llm.provider_management import (
        check_provider_dependency_installed,
        get_env_var_name,
        get_existing_api_key,
        get_valid_provider_names,
        update_env_file,
        validate_provider_name,
    )

    # Validate provider name
    provider_enum = validate_provider_name(provider)
    if not provider_enum:
        valid_names = ", ".join(get_valid_provider_names())
        console.print(
            f"[{theme.ERROR}]{t('ai.invalid_provider', provider=provider)}[/{theme.ERROR}]"
        )
        console.print(f"[dim]{t('ai.valid_providers', names=valid_names)}[/dim]")
        raise typer.Exit(1)

    console.print()
    console.print(f"[bold]{t('ai.switching_to', provider=provider)}[/bold]")
    console.print()

    # Check if dependency is installed
    if not check_provider_dependency_installed(provider):
        console.print(
            f"  [{theme.ERROR}]✗[/{theme.ERROR}] {t('ai.deps_not_installed', provider=provider)}"
        )
        console.print()
        console.print(f"[{theme.WARNING}]{t('ai.run_first')}[/{theme.WARNING}]")
        console.print(
            f"  [{theme.ACCENT}]aidb ai add-provider {provider}[/{theme.ACCENT}]"
        )
        raise typer.Exit(1)

    console.print(f"  [{theme.ACCENT}]✓[/{theme.ACCENT}] {t('ai.deps_ok')}")

    # Check API key (except for PUBLIC)
    if provider_enum != AIProvider.PUBLIC:
        env_var_name = get_env_var_name(provider)
        existing_key = get_existing_api_key(provider)

        if not existing_key:
            warning = t("ai.no_api_key_configured", var=env_var_name)
            console.print(f"  [{theme.WARNING}]![/{theme.WARNING}] {warning}")
            console.print()
            console.print(
                f"[{theme.WARNING}]{t('ai.consider_running')}[/{theme.WARNING}]"
            )
            console.print(
                f"  [{theme.ACCENT}]aidb ai add-provider {provider}[/{theme.ACCENT}]"
            )
            console.print(f"[dim]{t('ai.to_configure_key')}[/dim]")
            console.print()

            # Still allow switching, just warn
            confirm = typer.confirm(t("ai.switch_anyway"), default=False)
            if not confirm:
                raise typer.Exit(0)
        else:
            console.print(f"  [{theme.ACCENT}]✓[/{theme.ACCENT}] {env_var_name}")

    # Update AI_PROVIDER in .env
    update_env_file({"AI_PROVIDER": provider.lower()})

    console.print()
    console.print(
        f"[bold {theme.ACCENT}]{t('ai.switched_to', provider=provider)}[/bold {theme.ACCENT}]"
    )
    console.print()
    console.print(f"[dim]{t('ai.current_provider', provider=provider)}[/dim]")
