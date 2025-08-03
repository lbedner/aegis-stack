# Application Lifecycle

Aegis Stack provides a robust, composable system for managing application startup and shutdown events. This allows services to initialize and release resources cleanly, ensuring a stable and predictable application environment.

The lifecycle is managed by a single entrypoint: the `lifespan` context manager in `app/integrations/main.py`.

## The Lifecycle Registry

Instead of hardcoding logic into the `lifespan` manager, Aegis Stack uses a dynamic registry pattern. This allows any service to "hook into" the application lifecycle without modifying the core integration code.

The registry consists of two lists located in `app/core/lifecycle.py`:

- `STARTUP_TASKS`
- `SHUTDOWN_TASKS`

## Registering a New Task

To add a startup or shutdown task, a service simply needs to define a function and append it to the appropriate list.

For example, a hypothetical database service might do this:

```python
# app/services/database_service.py
from app.core.lifecycle import STARTUP_TASKS, SHUTDOWN_TASKS

async def connect_to_db():
    print("Connecting to database...")
    # ... connection logic ...

async def close_db_connection():
    print("Closing database connection...")
    # ... disconnection logic ...

# Register the functions
STARTUP_TASKS.append(connect_to_db)
SHUTDOWN_TASKS.append(close_db_connection)
```

## How it Works

1.  The application uses a **Service Discovery** mechanism to automatically import all modules within the `app/services` directory at startup.
2.  When a service module is imported, the code at its top level is executed. This is when the `STARTUP_TASKS.append(...)` calls happen.
3.  The `lifespan` manager then iterates through these populated lists, running all registered startup tasks.
4.  Upon shutdown, it iterates through the `SHUTDOWN_TASKS` in **reverse order** to ensure a clean teardown.

This pattern makes the system highly extensible. To add a new service with lifecycle hooks, you just drop a file into the `services` directory.