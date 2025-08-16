#!/usr/bin/env python3
"""
Aegis Stack CLI - Main entry point

Usage:
    aegis init PROJECT_NAME
    aegis components
    aegis --help
"""

from pathlib import Path

import typer

from aegis import __version__
from aegis.core.components import COMPONENTS, ComponentType, get_components_by_type
from aegis.core.dependency_resolver import DependencyResolver
from aegis.core.template_generator import TemplateGenerator

# Create the main Typer application
app = typer.Typer(
    name="aegis",
    help="Aegis Stack CLI - Component generation and project management",
    add_completion=False,
)


@app.command()
def version() -> None:
    """Show the Aegis Stack CLI version."""
    typer.echo(f"Aegis Stack CLI v{__version__}")


@app.command()
def components() -> None:
    """List available components and their dependencies."""

    typer.echo("\n📦 CORE COMPONENTS")
    typer.echo("=" * 40)
    typer.echo("  backend      - FastAPI backend server (always included)")
    typer.echo("  frontend     - Flet frontend interface (always included)")

    typer.echo("\n🏗️  INFRASTRUCTURE COMPONENTS")
    typer.echo("=" * 40)

    infra_components = get_components_by_type(ComponentType.INFRASTRUCTURE)
    for name, spec in infra_components.items():
        typer.echo(f"  {name:12} - {spec.description}")
        if spec.requires:
            typer.echo(f"               Requires: {', '.join(spec.requires)}")
        if spec.recommends:
            typer.echo(f"               Recommends: {', '.join(spec.recommends)}")

    typer.echo(
        "\n💡 Use 'aegis init PROJECT_NAME --components redis,worker' "
        "to select components"
    )


def validate_and_resolve_components(
    ctx: typer.Context, param: typer.CallbackParam, value: str | None
) -> list[str] | None:
    """Validate and resolve component dependencies."""
    if not value:
        return None

    # Parse comma-separated string
    selected = [c.strip() for c in value.split(",") if c.strip()]

    # Validate components exist
    errors = DependencyResolver.validate_components(selected)
    if errors:
        for error in errors:
            typer.echo(f"❌ {error}", err=True)
        raise typer.Exit(1)

    # Resolve dependencies
    resolved = DependencyResolver.resolve_dependencies(selected)

    # Show dependency resolution
    auto_added = DependencyResolver.get_missing_dependencies(selected)
    if auto_added:
        typer.echo(f"📦 Auto-added dependencies: {', '.join(auto_added)}")

    # Show recommendations
    recommendations = DependencyResolver.get_recommendations(resolved)
    if recommendations:
        rec_list = ", ".join(recommendations)
        typer.echo(f"💡 Recommended: {rec_list}")
        # Note: Skip interactive recommendations for now to keep it simple

    return resolved


@app.command()
def init(
    project_name: str = typer.Argument(
        ..., help="Name of the new Aegis Stack project to create"
    ),
    components: str | None = typer.Option(
        None,
        "--components",
        "-c",
        callback=validate_and_resolve_components,
        help="Comma-separated list of components (redis,worker,scheduler)",
    ),
    interactive: bool = typer.Option(
        True,
        "--interactive/--no-interactive",
        "-i/-ni",
        help="Use interactive component selection",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing directory if it exists"
    ),
    output_dir: str | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory to create the project in (default: current directory)",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """
    Initialize a new Aegis Stack project with battle-tested component combinations.

    This command creates a complete project structure with your chosen components,
    ensuring all dependencies and configurations are compatible and tested.

    Examples:\n
        - aegis init my-app\n
        - aegis init my-app --components redis,worker\n
        - aegis init my-app --components redis,worker,scheduler --no-interactive\n
    """

    typer.echo("🛡️  Aegis Stack Project Initialization")
    typer.echo("=" * 50)

    # Determine output directory
    base_output_dir = Path(output_dir) if output_dir else Path.cwd()
    project_path = base_output_dir / project_name

    typer.echo(f"📁 Project will be created in: {project_path.resolve()}")

    # Check if directory already exists
    if project_path.exists():
        if not force:
            typer.echo(f"❌ Directory '{project_path}' already exists", err=True)
            typer.echo(
                "   Use --force to overwrite or choose a different name", err=True
            )
            raise typer.Exit(1)
        else:
            typer.echo(f"⚠️  Overwriting existing directory: {project_path}")

    # Interactive component selection
    selected_components = components if components else []

    if interactive and not components:
        selected_components = interactive_component_selection()

        # Resolve dependencies for interactively selected components
        if selected_components:
            selected_components = DependencyResolver.resolve_dependencies(
                selected_components
            )

            auto_added = DependencyResolver.get_missing_dependencies(
                [c for c in selected_components if c not in ["backend", "frontend"]]
            )
            if auto_added:
                typer.echo(f"\n📦 Auto-added dependencies: {', '.join(auto_added)}")

    # Create template generator
    template_gen = TemplateGenerator(project_name, list(selected_components))

    # Show selected configuration
    typer.echo()
    typer.echo(f"📁 Project Name: {project_name}")
    typer.echo("🏗️  Project Structure:")
    typer.echo("   ✅ Core: backend, frontend")

    # Show infrastructure components
    infra_components = [
        name
        for name in selected_components
        if name in COMPONENTS and COMPONENTS[name].type == ComponentType.INFRASTRUCTURE
    ]
    if infra_components:
        typer.echo(f"   📦 Infrastructure: {', '.join(infra_components)}")

    # Show template files that will be generated
    template_files = template_gen.get_template_files()
    if template_files:
        typer.echo("\n📄 Component Files:")
        for file_path in template_files:
            typer.echo(f"   • {file_path}")

    # Show dependency information using template generator
    deps = template_gen._get_pyproject_deps()
    if deps:
        typer.echo("\n📦 Dependencies to be installed:")
        for dep in deps:
            typer.echo(f"   • {dep}")

    # Confirm before proceeding
    typer.echo()
    if not yes and not typer.confirm("🚀 Create this project?"):
        typer.echo("❌ Project creation cancelled")
        raise typer.Exit(0)

    # Create project using cookiecutter
    typer.echo()
    typer.echo(f"🔧 Creating project: {project_name}")

    try:
        from cookiecutter.main import cookiecutter

        # Get the template path
        template_path = (
            Path(__file__).parent / "templates" / "cookiecutter-aegis-project"
        )

        # Use template generator for context
        extra_context = template_gen.get_template_context()

        # Generate project with cookiecutter
        cookiecutter(
            str(template_path),
            extra_context=extra_context,
            output_dir=str(base_output_dir),
            no_input=True,  # Don't prompt user, use our context
            overwrite_if_exists=force,
        )

        typer.echo("✅ Project created successfully!")

        # Show next steps
        typer.echo()
        typer.echo("📋 Next steps:")
        typer.echo(f"   cd {project_path.resolve()}")
        typer.echo("   uv sync")
        typer.echo("   cp .env.example .env")
        typer.echo("   make run-local")

    except ImportError:
        typer.echo("❌ Error: cookiecutter not installed", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"❌ Error creating project: {e}", err=True)
        raise typer.Exit(1)


def interactive_component_selection() -> list[str]:
    """Interactive component selection with dependency awareness."""

    typer.echo("🎯 Component Selection")
    typer.echo("=" * 40)
    typer.echo("✅ Core components (backend + frontend) included automatically\n")

    selected = []

    # Infrastructure components
    typer.echo("🏗️  Infrastructure Components:")
    if typer.confirm("  Add Redis (caching, message queues)?"):
        selected.append("redis")

    if "redis" in selected:
        if typer.confirm("  Add worker infrastructure (background tasks)?"):
            selected.append("worker")
    else:
        if typer.confirm("  Add worker infrastructure? (will auto-add Redis)"):
            selected.extend(["redis", "worker"])

    if typer.confirm("  Add scheduler infrastructure (scheduled tasks)?"):
        selected.append("scheduler")

    return selected


# This is what runs when you do: aegis
if __name__ == "__main__":
    app()
