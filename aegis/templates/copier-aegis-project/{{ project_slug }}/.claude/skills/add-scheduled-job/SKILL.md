---
name: add-scheduled-job
description: Use when adding a job that runs on a schedule (periodic or at a fixed time) in this project. Covers writing the job function and listing it in its service's scheduled_jobs.py.
---

# Add scheduled job

Each service lists its scheduled work as `JOBS` in
`app/services/<service>/scheduled_jobs.py`; the scheduler finds every such
module on disk (`app.core.schedule.service_jobs`) and schedules every entry. In a
project with a worker, the scheduler only enqueues: each entry is scheduled as
an enqueue of the job's function name onto the system queue, and the worker
registers the same entry as a task under that name and runs it. Without a
worker, the scheduler runs the job itself.

## When to use

Use when work must run periodically or at a fixed time (a cron-like schedule).

Do NOT use for work triggered by a request (see the `add-background-job` skill
if a worker is present, or `add-api-endpoint` for a synchronous route).

## Files that change

- `app/services/<service>/jobs.py`: the job function, with the service it
  belongs to.
- `app/services/<service>/scheduled_jobs.py`: import the job function and add
  a `ServiceJob` entry to `JOBS` (function, id, name, trigger, and a
  `timeout` if a worker should let it run past the queue's five minutes).
  Create the file if the service has none; nothing else needs editing.

## Procedure

1. Write the failing test first for the job function's behavior, independent
   of the schedule. Confirm it fails for the right reason.
2. Write the job as an `async def` taking no arguments that does one unit of
   work.
3. Add a `ServiceJob` to the service's `JOBS`: the function, a stable id, a display
   name, and the trigger as `add_job` keyword arguments (for example
   `{"trigger": "cron", "hour": 3}`).
4. Keep the job idempotent: a schedule can fire late or twice, and a failed
   write-back runs it again, so a run must be safe to repeat.
5. Run the gates and fix anything red.

## Gates

- `make check`: lint, typecheck, and test. With a worker,
  `tests/components/test_scheduler_jobs.py` fails if a scheduled name is not a
  registered worker task.

## Pitfalls

- A job function that is not in some service's `JOBS` never runs.
- A `scheduled_jobs.py` without `JOBS`, or two entries sharing an id or a
  function name, fails at startup rather than scheduling the wrong thing.
- Do not call `scheduler.add_job(...)` for a service job in `main.py`: with a
  worker it would run in the scheduler process, outside the worker's limits
  and retries.
- The scheduler's run history times the enqueue when a worker is present; the
  job's own run time is on the worker's page.
