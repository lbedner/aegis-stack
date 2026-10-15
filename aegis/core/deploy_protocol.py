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
    ``at`` starting), for the deploy agent, which names the action it ran
    (``progress_env``). Only that action's steps: a command run inside
    another (a provision's deploy, a deploy's backup) leaves the bar to it.
    Nothing in a terminal."""
    action = os.environ.get(protocol.PROTOCOL["progress_env"], "")
    declared = protocol.PROTOCOL["actions"].get(action, {}).get("steps", {})
    if set(steps) <= declared.keys() and steps:
        typer.echo(protocol.progress_line(steps, at))
