"""
Validation functions for CLI inputs.

This module contains all validation logic for project names, components,
and other CLI inputs.
"""

import typer

from ..core.selection import project_name_rule
from . import brand


def validate_project_name(project_name: str) -> None:
    """Validate project name and raise typer.Exit if invalid."""
    rule = project_name_rule(project_name)
    if rule:
        brand.error(rule, err=True)
        raise typer.Exit(1)
