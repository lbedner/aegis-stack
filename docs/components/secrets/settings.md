# Settings

Credentials are only part of what an app is configured with. The rest (a health threshold, how long an account stays locked, the scheduler's timezone) also lives in `.env`, and changing one means editing a file on the server.

**Overseer > Settings** lists the settings marked for it, grouped by what reads them, each with its value, where it comes from (`.env`, the default, or saved here) and its default. With the secrets component installed, one that `.env` does not set can be saved from the page, the CLI or the API.

A saved setting applies when the app restarts. Code reads settings through `settings.NAME`, and each process (webserver, scheduler, worker) loads the saved values as it starts. A value set in `.env` still wins and shows as read-only, the same rule as Secrets.

Without the secrets component, the page still lists every setting with its source and default; values change in `.env`.

## Marking a setting

Annotate a field of `Settings` (`app/core/config.py`) with `Configurable`, naming what reads it. The page groups settings by that name:

```python
from typing import Annotated

from app.core.configurable import Configurable


class Settings(BaseSettings):
    # Before: CHECKOUT_RETRY_LIMIT: int = 3
    CHECKOUT_RETRY_LIMIT: Annotated[int, Configurable("Payments")] = 3
```

Code that reads it does not change: `settings.CHECKOUT_RETRY_LIMIT` is still an `int`. An optional second argument fills the page's **What** column:

```python
    CHECKOUT_RETRY_LIMIT: Annotated[
        int, Configurable("Payments", "Times a failed checkout is retried")
    ] = 3
```

## Values that come from a list

Every value is checked against the field's type before it is saved, so `lots` is refused for an `int`, with the reason, and is stored in one spelling (`true` saves as `True`).

When the type is a closed set, the page and the Flet dashboard show a list to pick from instead of a text field, set to the value in effect, and anything outside it is refused:

- a `bool` offers `True` and `False`;
- a `Literal["fast", "thorough"]` offers its values;
- an `Enum` offers its members' values.

For a plain type whose valid values are still a fixed list, name the list with `choices`, a function returning the values:

```python
from app.core.configurable import Configurable, timezones

SCHEDULER_TIMEZONE: Annotated[str, Configurable("Scheduler", choices=timezones)] = "UTC"
```

`timezones` returns every IANA timezone name, so the scheduler's timezone is picked from the list (searchable in Flet) and `Mars/Olympus` is refused. Your own list works the same way: `choices=lambda: ["eu", "us", "apac"]`.

## What to mark

A saved value reaches code that reads `settings.NAME` when it runs. Mark a setting only if all of these hold:

- **It is read inside a function, when the code runs.** A value copied once when a module is imported (a module-level constant, a class attribute, a default argument, a decorator argument) is fixed before the saved value is applied, so it would never change. The generated test `test_no_configurable_setting_is_read_at_import` scans `app/` and fails if a marked setting is read that way.
- **Nothing copies it into an object built at import.** A service created in a router module, for example `rag_service = RAGService(get_rag_config(settings))`, keeps the values it was built with. The test cannot see this one: check where the value ends up.
- **The app does not need it to start.** `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY` and `ENCRYPTION_KEY` are read before saved values can be loaded. So are the settings a process is launched with, such as the webserver engine or a worker's concurrency.
- **It is not a credential, or a provider's own setting.** Keys belong on the Secrets page, along with the settings that finish a provider's setup (a from address, a phone number).

Saved values apply in the webserver, the scheduler and the worker. A CLI command (`my-app ...`) reads `.env` only.

## Marked out of the box

| Owner | Settings |
|---|---|
| Health | `MEMORY_THRESHOLD_PERCENT`, `DISK_THRESHOLD_PERCENT`, `CPU_THRESHOLD_PERCENT`, `HEALTH_CHECK_TIMEOUT_SECONDS`, `SYSTEM_METRICS_CACHE_SECONDS` |
| Traffic | `TRAFFIC_MONITOR_ENABLED`, `TRAFFIC_WINDOW_HOURS`, `TRAFFIC_DOMINANCE_SHARE`, `TRAFFIC_DOMINANCE_FLOOR` |
| Auth | `ACCOUNT_LOCKOUT_ATTEMPTS`, `ACCOUNT_LOCKOUT_MINUTES` |
| Worker | `TASK_HISTORY_TTL_SECONDS`, `WORKER_MAX_REDELIVERIES` |
| Scheduler | `SCHEDULER_TIMEZONE` (picked from the IANA timezones) |
| AI | `AI_SENTIMENT_ENABLED`, `AI_SENTIMENT_BATCH_LIMIT` |
| Finance | `FINANCE_RULES_LOOKBACK_DAYS` |
| Insights | `INSIGHT_GITHUB_OWNER`, `INSIGHT_GITHUB_REPO`, `INSIGHT_PYPI_PACKAGE`, `INSIGHT_PROJECT_DESCRIPTION`, `INSIGHT_PROJECT_HOMEPAGE` |

Each only appears in a project that has what reads it. The rate limits are not on the list: the limiters are built when their module is imported. Neither are the AI provider and model, which the model picker and `llm use` already change without a restart.

## From the terminal

```bash
my-app settings list                              # value, source and default
my-app settings set MEMORY_THRESHOLD_PERCENT 80   # checked, applies on restart
my-app settings reset MEMORY_THRESHOLD_PERCENT    # back to the default
```

A setting is not a secret, so its value goes in as an argument and is shown whole.

## From the API

Settings use the secrets API: `GET /api/v1/secrets?setting=true` lists them (with `default`), and `PUT` / `DELETE /api/v1/secrets/{name}` save and remove a value. Like every secrets route, these are admin-only.
