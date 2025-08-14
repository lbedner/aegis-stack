#!/usr/bin/env python3
"""
Aegis Stack CLI - Main entry point

Usage:
    aegis init PROJECT_NAME
    aegis --help
"""

from enum import Enum
from pathlib import Path

import typer


# Define available components as an Enum
# This automatically creates choices for Typer and provides validation
class ComponentType(str, Enum):
    """Available component types for Aegis Stack."""

    scheduler = "scheduler"
    database = "database"
    cache = "cache"


# Create the main Typer application
# help= sets the description shown in --help
app = typer.Typer(
    name="aegis",
    help="Aegis Stack CLI - Component generation and project management",
    add_completion=False,  # We'll add this later
)


@app.command()
def version() -> None:
    """Show the Aegis Stack CLI version."""
    from aegis import __version__

    typer.echo(f"Aegis Stack CLI v{__version__}")


@app.command()
def init(
    project_name: str = typer.Argument(
        ..., help="Name of the new Aegis Stack project to create"
    ),
    components: str | None = typer.Option(
        None,
        "--components",
        "-c",
        help="Comma-separated list of components (scheduler,database,cache)",
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
        - aegis init my-app --components scheduler,database\n
        - aegis init my-app --components scheduler,database,cache --no-interactive\n
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

    # Parse components from command line
    selected_components = set()
    if components:
        component_list = [c.strip() for c in components.split(",")]
        for comp in component_list:
            try:
                selected_components.add(ComponentType(comp))
            except ValueError as e:
                typer.echo(f"❌ Invalid component: {comp}", err=True)
                typer.echo(f"   Error: {str(e)}", err=True)
                valid_components = [c.value for c in ComponentType]
                typer.echo(
                    f"   Valid components: {', '.join(valid_components)}", err=True
                )
                raise typer.Exit(1)

    # Interactive component selection
    if interactive and not components:
        typer.echo("🧩 Select components for your project:")
        typer.echo("   (Core components: backend, frontend are always included)")
        typer.echo()

        # Show available components with descriptions
        component_descriptions = {
            ComponentType.scheduler: "APScheduler-based async task scheduling",
            ComponentType.database: "SQLAlchemy + asyncpg for PostgreSQL",
            ComponentType.cache: "Redis-based async caching",
        }

        for comp_type in ComponentType:
            description = component_descriptions[comp_type]

            # Ask user for each component
            include = typer.confirm(
                f"   Include {comp_type.value}? ({description})", default=False
            )
            if include:
                selected_components.add(comp_type)

    # Show selected configuration
    typer.echo()
    typer.echo(f"📁 Project Name: {project_name}")
    typer.echo("🏗️  Project Structure:")
    typer.echo("   ✅ Core (backend: FastAPI, frontend: Flet)")

    if selected_components:
        typer.echo("   ✅ Additional Components:")
        for comp in sorted(selected_components, key=lambda x: x.value):
            typer.echo(f"      • {comp.value}")
    else:
        typer.echo("   📦 No additional components selected")

    # Show what will be created
    typer.echo()
    typer.echo("📄 Files to be generated:")

    # Always created (core files)
    core_files = [
        "pyproject.toml",
        "README.md",
        "Dockerfile",
        "docker-compose.yml",
        ".env.example",
        "app/components/backend/",
        "app/components/frontend/",
        "app/core/",
        "app/integrations/",
        "tests/",
        "docs/",
    ]

    for file_path in core_files:
        typer.echo(f"   • {file_path}")

    # Component-specific files
    if ComponentType.scheduler in selected_components:
        typer.echo("   • app/components/scheduler.py")
        typer.echo("   • tests/components/test_scheduler.py")

    if ComponentType.database in selected_components:
        typer.echo("   • app/services/database_service.py")
        typer.echo("   • app/models/")
        typer.echo("   • tests/test_database.py")
        typer.echo("   • alembic/")

    if ComponentType.cache in selected_components:
        typer.echo("   • app/services/cache_service.py")
        typer.echo("   • tests/test_cache.py")

    # Show dependency information
    typer.echo()
    typer.echo("📦 Dependencies to be installed:")

    # Core dependencies (always included)
    core_deps = [
        "fastapi",
        "flet[all]",
        "uvicorn",
        "structlog",
        "pydantic-settings",
        "typer",
    ]
    for dep in core_deps:
        typer.echo(f"   • {dep}")

    # Component dependencies
    if ComponentType.scheduler in selected_components:
        typer.echo("   • apscheduler")

    if ComponentType.database in selected_components:
        for dep in ["sqlalchemy[asyncio]", "asyncpg", "alembic"]:
            typer.echo(f"   • {dep}")

    if ComponentType.cache in selected_components:
        typer.echo("   • redis[hiredis]")

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

        # Prepare cookiecutter context
        # Extract just the project name from the path
        clean_project_name = Path(project_name).name
        extra_context = {
            "project_name": clean_project_name.replace("-", " ")
            .replace("_", " ")
            .title(),
            "project_slug": clean_project_name,
            "include_scheduler": "yes"
            if ComponentType.scheduler in selected_components
            else "no",
            "include_database": "yes"
            if ComponentType.database in selected_components
            else "no",
            "include_cache": "yes"
            if ComponentType.cache in selected_components
            else "no",
        }

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


# This is what runs when you do: aegis
if __name__ == "__main__":
    app()
