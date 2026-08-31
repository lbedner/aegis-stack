"""
Default configuration values for Aegis Stack.

These values are derived from the aegis-stack pyproject.toml to maintain
a single source of truth.
"""

import re
from pathlib import Path


def _parse_python_version_bounds() -> tuple[str, str]:
    """
    Parse Python version bounds from aegis-stack's pyproject.toml.

    Extracts requires-python (e.g., ">=3.11,<3.15") and returns:
    - Lower bound (minimum supported): "3.11"
    - Upper bound (maximum supported): "3.14" (derived from <3.15)

    Returns:
        Tuple of (min_version, max_version) as strings

    Note:
        Falls back to ("3.11", "3.14") if parsing fails.
    """
    try:
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            content = pyproject_path.read_text()
            for line in content.splitlines():
                if "requires-python" in line and ">=" in line:
                    # Parse: requires-python = ">=3.11,<3.14"
                    # Extract the version spec
                    spec = line.split("=", 1)[1].strip().strip('"')

                    # Lower bound: >=3.11 → 3.11
                    lower = spec.split(">=")[1].split(",")[0].strip()

                    # Upper bound: <3.14 → 3.13 (max supported version)
                    if "<" in spec:
                        upper_spec = spec.split("<")[1].strip()
                        major, minor = upper_spec.split(".")
                        # <3.14 means max supported is 3.13
                        upper = f"{major}.{int(minor) - 1}"
                    else:
                        upper = lower  # Fallback if no upper bound

                    return (lower, upper)
    except (FileNotFoundError, OSError, ValueError, IndexError):
        pass

    # Fallback defaults
    return ("3.11", "3.14")


def _generate_supported_versions(min_version: str, max_version: str) -> list[str]:
    """
    Generate list of supported Python versions from min to max.

    Args:
        min_version: Minimum version (e.g., "3.11")
        max_version: Maximum version (e.g., "3.14")

    Returns:
        List of version strings (e.g., ["3.11", "3.12", "3.13", "3.14"])

    Note:
        Only works for same major version. Falls back to hardcoded list
        if major versions differ (e.g., 3.x → 4.x transition).
    """
    try:
        min_parts = min_version.split(".")
        max_parts = max_version.split(".")

        # Only works if same major version
        if min_parts[0] != max_parts[0]:
            return ["3.11", "3.12", "3.13", "3.14"]  # Fallback

        major = min_parts[0]
        min_minor = int(min_parts[1])
        max_minor = int(max_parts[1])

        return [f"{major}.{i}" for i in range(min_minor, max_minor + 1)]
    except (ValueError, IndexError):
        return ["3.11", "3.12", "3.13"]  # Fallback


# Parse bounds from pyproject.toml (single source of truth)
_min_version, _max_version = _parse_python_version_bounds()

# Default Python version for generated projects: the newest supported
# version. Users can pick any entry in SUPPORTED_PYTHON_VERSIONS via
# ``--python-version``.
DEFAULT_PYTHON_VERSION = _max_version

# Supported Python versions (auto-generated from min to max)
SUPPORTED_PYTHON_VERSIONS = _generate_supported_versions(_min_version, _max_version)


def version_to_git_tag(version: str) -> str:
    """
    Convert a PEP 440 version string to a git tag.

    PEP 440 uses no separator before pre-release identifiers (e.g., 0.6.0rc1),
    but our git tags use a dash (e.g., v0.6.0-rc1).

    Accepts either a PEP 440 version ("0.6.0rc1") or an already-tagged
    form ("v0.6.0-rc1"); a leading "v" is stripped first so the result is
    idempotent (passing a tag back in won't produce "vv0.6.0-rc1").

    Args:
        version: PEP 440 version string (e.g., "0.6.0rc1", "0.5.4") or a
            git tag (e.g., "v0.6.0-rc1")

    Returns:
        Git tag string (e.g., "v0.6.0-rc1", "v0.5.4")
    """
    # Strip a single leading "v" so tag-form input round-trips cleanly.
    if version.startswith("v"):
        version = version[1:]
    # Insert dash before pre-release identifiers: rc, alpha, beta, dev
    # Negative lookbehind ensures we don't double-dash if already present
    normalized = re.sub(r"(?<!-)(rc|alpha|beta|dev)(\d+)", r"-\1\2", version)
    return f"v{normalized}"


# GitHub URL for template source (used when installed via pip/uvx)
GITHUB_TEMPLATE_URL = "gh:lbedner/aegis-stack"

# GitHub repository URL (for commit links, documentation links, etc.)
GITHUB_REPO_URL = "https://github.com/lbedner/aegis-stack"
