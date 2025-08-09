"""
Main CLI application entry point.

Command-line interface for {{cookiecutter.project_name}} management tasks.
"""

import typer

from app.cli import health

app = typer.Typer(
    name="{{cookiecutter.project_slug}}",
    help="{{cookiecutter.project_name}} management CLI",
    no_args_is_help=True,
)

# Register sub-commands
app.add_typer(health.app, name="health")


def main() -> None:
    """Entry point for the CLI application."""
    app()


if __name__ == "__main__":
    main()
