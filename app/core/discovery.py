# app/core/discovery.py
"""
A utility for dynamically discovering and importing modules from a given package.
This enables a "drop-in" plugin architecture for services.
"""

import importlib
import pkgutil
from pathlib import Path

from app.core.log import logger


def discover_and_import_services(package_path: str | Path) -> None:
    """
    Dynamically discovers and imports all modules in a given package path.

    This function iterates through a package, constructs the full module path
    for each submodule, and imports it. This triggers the execution of the
    module's top-level code, allowing services to self-register with registries
    like the lifecycle manager.

    Args:
        package_path: The filesystem path to the package to be discovered.
    """
    # Get the project's root directory to calculate the relative path
    project_root = Path.cwd()
    relative_path = Path(package_path).relative_to(project_root)

    # Convert the relative filesystem path to a Python package name
    # (e.g., "app/services")
    package_name = ".".join(relative_path.parts)
    logger.info(f"--- Discovering services in '{package_name}' ---")

    for _, module_name, _ in pkgutil.walk_packages([str(package_path)]):
        # Skip any private modules (e.g., _internal_utils.py)
        if module_name.startswith("_"):
            continue

        # Construct the full module path
        full_module_path = f"{package_name}.{module_name}"

        # Import the module
        try:
            importlib.import_module(full_module_path)
            logger.info(f"Successfully imported service: {module_name}")
        except Exception as e:
            logger.error(f"Failed to import service: {module_name}, Error: {e}")
