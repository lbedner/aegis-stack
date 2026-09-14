"""
Version compatibility utilities for CLI and project template version management.

This module provides version detection, comparison, and compatibility checking
to handle the uvx version mismatch scenario where users may run a newer CLI
version against an older project template version.
"""

from enum import Enum
from pathlib import Path

import typer
from packaging.version import Version, parse

from aegis import __version__ as cli_version  # noqa: N813
from aegis.core.copier_manager import load_copier_answers
from aegis.core.copier_updater import (
    get_available_versions,
    get_commit_for_version,
    get_current_template_commit,
    get_template_root,
)

from ..cli import brand


class VersionCompatibility(Enum):
    """Version compatibility status between CLI and project."""

    COMPATIBLE = "compatible"  # Same or patch difference
    MINOR_MISMATCH = "minor_mismatch"  # Minor version difference
    MAJOR_MISMATCH = "major_mismatch"  # Major version difference
    UNKNOWN = "unknown"  # Cannot determine (missing version info)


def get_cli_version() -> str:
    """
    Get the current CLI version.

    Returns:
        Version string (e.g., "0.2.0")
    """
    return cli_version


def get_project_template_version(project_path: Path) -> str | None:
    """
    Get the template version used to generate the project.

    First checks for _template_version field in .copier-answers.yml (explicit).
    Falls back to matching _commit hash to version tags in template repository.

    Args:
        project_path: Path to the project directory

    Returns:
        Version string if found, None if cannot determine
    """
    try:
        # First, check for explicit _template_version in answers
        # This is set by newer versions of aegis init
        answers = load_copier_answers(project_path)
        if answers and "_template_version" in answers:
            return answers["_template_version"]

        # Fall back to commit-based version detection
        # Get the commit hash used to generate the project
        commit_hash = get_current_template_commit(project_path)
        if not commit_hash:
            return None

        # Try to match commit to a version tag
        template_root = get_template_root()

        # Get all available versions and check if any match this commit
        for version in get_available_versions(template_root):
            version_commit = get_commit_for_version(version, template_root)
            if version_commit == commit_hash:
                return version

        # No matching version tag found - project might be generated
        # from a commit between releases. For now, return None.
        # Could potentially return the latest version before this commit.
        return None

    except Exception:
        return None


def parse_version_safe(version_str: str) -> Version | None:
    """
    Safely parse a version string.

    Args:
        version_str: Version string to parse

    Returns:
        Parsed Version object or None if invalid
    """
    try:
        return parse(version_str)
    except Exception:
        return None


def check_version_compatibility(
    cli_version: str, project_version: str | None
) -> VersionCompatibility:
    """
    Check compatibility between CLI version and project template version.

    Uses semantic versioning rules:
    - Patch difference (0.1.0 → 0.1.5): Compatible
    - Minor difference (0.1.0 → 0.2.0): Warning
    - Major difference (0.x.x → 1.x.x): Block

    Args:
        cli_version: CLI version string
        project_version: Project template version string (or None)

    Returns:
        VersionCompatibility enum value
    """
    if not project_version:
        return VersionCompatibility.UNKNOWN

    cli_ver = parse_version_safe(cli_version)
    proj_ver = parse_version_safe(project_version)

    if not cli_ver or not proj_ver:
        return VersionCompatibility.UNKNOWN

    # Extract major/minor versions
    cli_major = cli_ver.major
    cli_minor = cli_ver.minor
    proj_major = proj_ver.major
    proj_minor = proj_ver.minor

    # Major version mismatch
    if cli_major != proj_major:
        return VersionCompatibility.MAJOR_MISMATCH

    # Minor version mismatch
    if cli_minor != proj_minor:
        return VersionCompatibility.MINOR_MISMATCH

    # Same major.minor (patch differences are compatible)
    return VersionCompatibility.COMPATIBLE


def format_version_warning(
    cli_version: str,
    project_version: str,
    compatibility: VersionCompatibility,
    command_name: str = "add",
) -> str:
    """
    Format a user-friendly version mismatch warning with escape hatches.

    Provides three options:
    1. Update project to match CLI version
    2. Pin CLI version to match project
    3. Force through with --force flag

    Args:
        cli_version: Current CLI version
        project_version: Project template version
        compatibility: Compatibility status
        command_name: Command being run (for messaging)

    Returns:
        Formatted warning message
    """
    lines = [
        "",
        "Version Mismatch Detected",
        "=" * 50,
        f"CLI Version:      {cli_version}",
        f"Project Version:  {project_version}",
        "",
    ]

    if compatibility == VersionCompatibility.MAJOR_MISMATCH:
        lines.extend(
            [
                "Major version mismatch - update required",
                "",
                "The CLI version has breaking changes. You must:",
                f"  1. Update project:  aegis update --to-version {cli_version}",
                f"  2. Pin CLI version: uvx aegis-stack@{project_version} {command_name} ...",
                "",
                "Major version updates may require manual migration steps.",
            ]
        )
    elif compatibility == VersionCompatibility.MINOR_MISMATCH:
        lines.extend(
            [
                "Minor version mismatch - review recommended",
                "",
                "Choose one option:",
                "  1. Update project:  aegis update",
                f"  2. Pin CLI version: uvx aegis-stack@{project_version} {command_name} ...",
                f"  3. Force through:   aegis {command_name} ... --force",
                "",
                "Option 1 (recommended): Get latest template improvements",
                "Option 2 (safest):      Match CLI to your project version",
                "Option 3 (risky):       Proceed without updating",
            ]
        )

    lines.append("")
    return "\n".join(lines)


def validate_version_compatibility(
    project_path: Path, command_name: str = "add", force: bool = False
) -> None:
    """
    Validate CLI and project version compatibility, exit if incompatible.

    This function checks version compatibility and:
    - Allows: Same version or patch differences
    - Warns + blocks: Minor version differences (unless --force)
    - Blocks: Major version differences

    Args:
        project_path: Path to project directory
        command_name: Name of command being run
        force: Whether to bypass minor version warnings

    Raises:
        typer.Exit: If versions are incompatible
    """
    cli_version = get_cli_version()
    project_version = get_project_template_version(project_path)

    # Skip check if we can't determine project version
    if not project_version:
        return

    compatibility = check_version_compatibility(cli_version, project_version)

    # Compatible versions - no action needed
    if compatibility == VersionCompatibility.COMPATIBLE:
        return

    # The recorded version isn't a version at all (a project stamped with a
    # bare ref like ``HEAD``). Nothing can be compared, so nothing is
    # blocked — but say so, or this project is silently never gated again,
    # across a major version included (#1136).
    if compatibility == VersionCompatibility.UNKNOWN:
        brand.warn(
            f"\nWarning: project template version {project_version!r} is not a "
            f"version, so it cannot be checked against the CLI ({cli_version}).\n"
            f"Run 'aegis update --to-version {cli_version}' to restamp it.\n"
        )
        return

    # Major version mismatch - always block
    if compatibility == VersionCompatibility.MAJOR_MISMATCH:
        warning = format_version_warning(
            cli_version, project_version, compatibility, command_name
        )
        typer.echo(warning, err=True)
        raise typer.Exit(1)

    # Minor version mismatch - warn and block unless --force
    if compatibility == VersionCompatibility.MINOR_MISMATCH:
        if not force:
            warning = format_version_warning(
                cli_version, project_version, compatibility, command_name
            )
            typer.echo(warning, err=True)
            raise typer.Exit(1)
        else:
            # Show warning but allow through with --force
            brand.warn(
                f"\nWarning: Forcing through version mismatch "
                f"(CLI: {cli_version}, Project: {project_version})\n"
            )
