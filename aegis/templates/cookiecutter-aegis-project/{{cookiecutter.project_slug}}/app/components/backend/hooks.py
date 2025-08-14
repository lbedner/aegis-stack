# app/components/backend/hooks.py
"""
Backend-specific hook management system for drop-in extensibility.

This system automatically discovers and registers:
- Middleware from app/components/backend/middleware/
- Startup hooks from app/components/backend/startup/
- Shutdown hooks from app/components/backend/shutdown/

Just drop files in the appropriate folders - no central registration required.
"""

from collections.abc import Callable
import importlib
import inspect
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.core.log import logger


class BackendHooks:
    """Backend-specific hook management system."""

    def __init__(self) -> None:
        self.startup_hooks: list[Callable[[], Any]] = []
        self.shutdown_hooks: list[Callable[[], Any]] = []

    def discover_and_register_middleware(self, app: FastAPI) -> None:
        """
        Auto-discover and register middleware. This must be called
        before the application starts.
        """
        middleware_dir = Path(__file__).parent / "middleware"
        if not middleware_dir.exists():
            return

        for middleware_file in middleware_dir.glob("*.py"):
            if middleware_file.name.startswith("_"):
                continue

            module_name = f"app.components.backend.middleware.{middleware_file.stem}"
            try:
                module = importlib.import_module(module_name)
                if hasattr(module, "register_middleware"):
                    logger.info(f"Registering middleware from {module_name}")
                    # Middleware registration is synchronous
                    module.register_middleware(app)
            except Exception as e:
                logger.error(f"Failed to load middleware {module_name}: {e}")

    async def discover_lifespan_hooks(self) -> None:
        """Discover startup and shutdown hooks for the lifespan event."""
        await self._discover_startup_hooks()
        await self._discover_shutdown_hooks()

    async def _discover_startup_hooks(self) -> None:
        """Auto-discover startup hooks from app/components/backend/startup/."""
        startup_dir = Path(__file__).parent / "startup"
        if not startup_dir.exists():
            logger.info("No backend startup directory found")
            return

        for startup_file in startup_dir.glob("*.py"):
            if startup_file.name.startswith("_"):
                continue

            module_name = f"app.components.backend.startup.{startup_file.stem}"
            try:
                module = importlib.import_module(module_name)

                # Look for startup_hook function
                if hasattr(module, "startup_hook"):
                    logger.info(f"Registered startup hook from {module_name}")
                    self.startup_hooks.append(module.startup_hook)

            except Exception as e:
                logger.error(f"Failed to load startup hook {module_name}: {e}")

    async def _discover_shutdown_hooks(self) -> None:
        """Auto-discover shutdown hooks from app/components/backend/shutdown/."""
        shutdown_dir = Path(__file__).parent / "shutdown"
        if not shutdown_dir.exists():
            logger.info("No backend shutdown directory found")
            return

        for shutdown_file in shutdown_dir.glob("*.py"):
            if shutdown_file.name.startswith("_"):
                continue

            module_name = f"app.components.backend.shutdown.{shutdown_file.stem}"
            try:
                module = importlib.import_module(module_name)

                # Look for shutdown_hook function
                if hasattr(module, "shutdown_hook"):
                    logger.info(f"Registered shutdown hook from {module_name}")
                    self.shutdown_hooks.append(module.shutdown_hook)

            except Exception as e:
                logger.error(f"Failed to load shutdown hook {module_name}: {e}")

    async def execute_startup_hooks(self) -> None:
        """Execute all discovered startup hooks."""
        logger.info(f"Executing {len(self.startup_hooks)} backend startup hooks")
        for hook in self.startup_hooks:
            try:
                if inspect.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
            except Exception as e:
                logger.error(f"Startup hook failed: {e}")
                raise

    async def execute_shutdown_hooks(self) -> None:
        """Execute all discovered shutdown hooks in reverse order."""
        logger.info(f"Executing {len(self.shutdown_hooks)} backend shutdown hooks")
        for hook in reversed(self.shutdown_hooks):
            try:
                if inspect.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
            except Exception as e:
                logger.error(f"Shutdown hook failed: {e}")
                # Continue with other shutdown hooks even if one fails


# Global backend hooks instance
backend_hooks = BackendHooks()
