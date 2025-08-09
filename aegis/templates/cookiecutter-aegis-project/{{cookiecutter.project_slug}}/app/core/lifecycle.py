# app/core/lifecycle.py
"""
A simple, lightweight registry for application startup and shutdown tasks.

To add a new task, simply append it to the STARTUP_TASKS or SHUTDOWN_TASKS list.
The main application lifecycle will execute these tasks in the order they are
registered.
"""

from collections.abc import Awaitable, Callable

# Type alias for a callable that returns an awaitable (e.g., an async function)
LifecycleTask = Callable[[], Awaitable[None]]

STARTUP_TASKS: list[LifecycleTask] = []
SHUTDOWN_TASKS: list[LifecycleTask] = []
