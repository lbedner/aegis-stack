"""The deploy agent's protocol: the template's own
``app/components/deploy/protocol.py``, one copy for the app and the CLI,
loaded once here so every command (the agent, a provision, a backup) can
reach it without importing another command.
"""

import os

import typer

from .component_files import template_module

protocol = template_module(
    "aegis_deploy_protocol", "app", "components", "deploy", "protocol.py"
)


def step(steps: list[str], at: str) -> None:
    """Where the step bar stands (``progress_line``: the plan, and the step
    ``at`` starting), for the deploy agent; nothing in a terminal."""
    if os.environ.get(protocol.PROTOCOL["progress_env"]):
        typer.echo(protocol.progress_line(steps, at))
