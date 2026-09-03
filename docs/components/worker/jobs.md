# Background Jobs

A worker runs the work. **Jobs** are how the rest of the application - an API caller, a dashboard, a page you have not navigated away from yet - knows what happened to it.

!!! info "Two Halves, Deliberately"
    A **task** is what the worker executes. A **job record** is a small, readable summary of one run: its name, its status, the label it is currently narrating, and its result. The task can only be seen by the worker; the job record can be read by anyone, from any process.

## What You Get

- **`GET /api/v1/jobs`** - every job the process knows about, running first, newest first
- **`GET /api/v1/jobs/{id}`** - one job's current state
- **Two SSE streams** - `/api/v1/jobs/events` for all of them, `/api/v1/jobs/{id}/events` for one
- **The same shape either way** - a job that ran in-process and a job that ran on a worker are the same record, so a caller never asks which happened
- **`follow_job` / `follow_jobs`** - the Flet side of those streams, for a progress line or a live table

## The Record

```json
{
  "job_id": "cc35bde2881648deae8642057b15f921",
  "name": "documents-extract:2",
  "status": "running",
  "label": "Reading page 3 of 7...",
  "result": null,
  "error": null,
  "started_at": "2026-09-02T20:13:24.220336+00:00"
}
```

| Field | Means |
|-------|-------|
| `name` | what this job is, in the service's own terms - `<service>-<verb>:<subject>` reads well in a table |
| `status` | `running`, `done`, or `failed` |
| `label` | the one line the work is currently narrating; the only thing that changes while it runs |
| `result` | whatever the work returned, on `done` |
| `error` | the raised exception's message, on `failed` |

The label is the whole progress mechanism. There is no percentage, because a percentage is a promise about work nobody has done yet; a sentence that says which page is being read is honest and just as useful.

## Where a Job Runs

```
service.start_x()
      |
      +-- worker in this stack?  --> enqueue the task; the worker writes the record
      |                              to Redis as it goes
      |
      +-- no worker?             --> run it here as an asyncio task; the runner
                                     holds the record in memory
```

Both paths return a job id immediately, and both feed the same API. A project that adds a worker later changes nothing about how its jobs are watched.

!!! warning "In-process jobs live and die with the process"
    Without a worker, a job's record is in memory: a restart loses it, and the runner keeps only the most recent finished jobs. With a worker the record is a Redis hash with a six-hour expiry, and any process can read it - which is what lets the web server narrate work it is not doing.

## Adding a Job to a Service

Three pieces, and the first two are the ones your service already has.

**1. The work.** A coroutine that reports as it goes and returns a result:

```python
async def import_statements(account_id: int, *, report) -> dict[str, int]:
    for n, row in enumerate(rows, start=1):
        report(f"Importing row {n} of {len(rows)}...")
        ...
    return {"imported": len(rows)}
```

**2. The in-process path**, for a stack with no worker:

```python
from app.services.system.jobs import JobHandle, get_job_runner


async def start_import_in_process(account_id: int) -> str:
    async def work(handle: JobHandle) -> dict[str, int]:
        return await import_statements(account_id, report=handle.set_label)

    return get_job_runner().start(
        f"finance-import:{account_id}", work, label="Opening the file..."
    )
```

**3. The worker path**, when the stack has one. The task writes the same record to the shared store, and dispatch picks between them at import time:

```python
{%- if include_worker %}
async def start_import(account_id: int) -> str:
    ...  # create the record, then enqueue the task
{%- else %}
start_import = start_import_in_process
{%- endif %}
```

`app/services/documents/domains/extraction/dispatch.py` is the worked example, and the shape is deliberately small: one task, one dispatch function, one job name.

!!! tip "A job's name is a contract with the UI"
    `documents-extract:2` is parsed by the Activity tab to know which document a row belongs to. Pick a name a surface can read, and keep it stable.

## Watching a Job

From anything that speaks HTTP:

```bash
curl -N http://localhost:8000/api/v1/jobs/$JOB/events
```

```
event: status
data: {"job_id": "...", "status": "running", "label": "Reading page 3 of 7..."}

event: status
data: {"job_id": "...", "status": "done", "result": {"read": 7}}
```

The stream sends the current state first, then every change, then exactly one terminal frame and closes. A client reads until the terminal status; it never has to poll.

From a Flet surface:

```python
from app.components.frontend.controls.jobs import follow_job, follow_jobs

# one job, narrating into a label
outcome = await follow_job(api, job_id, on_label=lambda text: self._set(text))

# every job, for a live table
await follow_jobs(api, on_snapshot=self._render_row)
```

## Configuration

Nothing to configure. With a worker present the job store uses the same `REDIS_URL` the queues use, keeps records for six hours, and is attached at startup.

## Next Steps

| Topic | Description |
|-------|-------------|
| **[Getting Started](index.md)** | Adding a worker, choosing a backend, writing tasks |
| **[Configuration](configuration.md)** | Queues, concurrency, timeouts |
| **[Examples](examples.md)** | Task patterns end to end |

---

**Related:**

- **[Documents Service](../../services/documents/extraction.md)** - the worked example: extraction on the worker when there is one
- **[Overseer](../../overseer/index.md)** - where jobs are watched in the dashboard
