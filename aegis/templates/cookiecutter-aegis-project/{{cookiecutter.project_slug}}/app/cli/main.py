"""
Main CLI application entry point.

Command-line interface for full-stack management tasks.
"""

import typer

from app.cli import health, load_test

app = typer.Typer(
    name="full-stack",
    help="full-stack management CLI",
    no_args_is_help=True,
)

# Register sub-commands
app.add_typer(health.app, name="health")
app.add_typer(load_test.app, name="load-test")


def main() -> None:
    """Entry point for the CLI application."""
    app()


if __name__ == "__main__":
    main()
