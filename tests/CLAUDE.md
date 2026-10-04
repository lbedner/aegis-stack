# Testing Guide for Aegis Stack

## Stack Cache Fixture (CRITICAL for Test Performance)

**IMPORTANT: When adding new stack configurations (components or services), you MUST add corresponding cache entries to avoid 10+ minute test times!**

### How It Works

The test infrastructure uses a two-tier caching system in `tests/cli/conftest.py`:

1. **`project_template_cache`** (session-scoped): Generates project skeletons ONCE per test session
2. **`project_factory`** (per-test): Copies cached skeletons into fresh temp directories

This avoids regenerating the same project configuration for every test that needs it.

There is a SECOND generation lane: `generated_stacks` builds the
`STACK_COMBINATIONS` matrix (test_stack_generation / test_stack_validation)
via full `aegis init` runs. It is **lazy + session-memoized**: a stack is
generated on first request and reused, so scoped runs only pay for the stacks
their tests touch. Two rules when adding a matrix row:

- Every new `StackCombination` adds a full init (render + uv sync + make fix
  + migrations, 10-40s) to every PR: `test_stack_generation.py` is marked
  `slow` and runs in CI's own `generation` jobs on every PR (`make
  test-stacks` locally), not in `make test`. Add rows only for genuinely new
  coverage.
- Do not build a second near-identical config: if factory-based tests need the
  same stack, use a `NAMED_PROJECT_SPECS` entry (copied per test), not another
  matrix row.

### CI shards: `--shard K/N`

CI (`ci.yml`) runs the fast lane as two parallel jobs (`test 1/2`, `test 2/2`,
gated by one `test` check) and stack generation as four (`generation 1/4`..`4/4`,
gated by `generation`).
`--shard K/N` (`tests/conftest.py`) keeps the K-th of N slices by a stable hash.
What must share a process stays together: a stack's parametrized tests (keyed
on the `combination` param, so each stack generates once) and every
`xdist_group`. Anything else splits by file, so a new expensive file lands in
one shard; run `pytest -m "not slow" --collect-only -q -o addopts= --shard K/2`
to see where. Locally nothing changes: without `--shard` every test runs.

### Cache Configuration: `NAMED_PROJECT_SPECS`

All cached stack configurations are defined in `tests/cli/conftest.py`:

```python
NAMED_PROJECT_SPECS: dict[str, ProjectTemplateSpec] = {
    # Component-based
    "base": ProjectTemplateSpec(),
    "base_with_database": ProjectTemplateSpec(components=("database",)),
    "base_with_scheduler": ProjectTemplateSpec(components=("scheduler",)),
    "base_with_scheduler_sqlite": ProjectTemplateSpec(
        components=("database", "scheduler"), scheduler_backend="sqlite"
    ),
    "base_with_worker": ProjectTemplateSpec(components=("worker",)),
    "base_with_redis": ProjectTemplateSpec(components=("redis",)),
    "scheduler_and_database": ProjectTemplateSpec(components=("database", "scheduler")),
    # Service-based
    "base_with_auth_service": ProjectTemplateSpec(services=("auth",)),
    "base_with_ai_service": ProjectTemplateSpec(services=("ai",)),
    "base_with_ai_sqlite_service": ProjectTemplateSpec(services=("ai[sqlite]",)),
    "base_with_auth_and_ai_services": ProjectTemplateSpec(services=("auth", "ai")),
}
```

### When to Add Cache Entries

**Add a new entry when:**
- You create a new service (e.g., `ai`, `comms`)
- You create a new component combination that tests need
- Multiple tests need the same stack configuration

**Signs you need a new cache entry:**
- Tests are slow because they call `run_aegis_command("init", ...)` directly
- The same stack configuration is generated in multiple tests

### Using the Cache in Tests

```python
from tests.cli.conftest import ProjectFactory

class TestMyFeature:
    def test_something(self, project_factory: ProjectFactory) -> None:
        # Get a cached copy of a base project (fast - just copies files)
        project_path = project_factory("base")

        # Now do your test (e.g., add-service, modify files, etc.)
        result = run_aegis_command("add-service", "auth", "--project-path", str(project_path))

    def test_with_ai(self, project_factory: ProjectFactory) -> None:
        # Get a cached copy of AI service project
        project_path = project_factory("base_with_ai_service")
```

### Performance Impact

- **Without cache:** Each test regenerates project from scratch (~30-40 seconds)
- **With cache:** First test generates, subsequent tests copy (~1-2 seconds)
- **Total impact:** Can reduce test suite from 10+ minutes to 2-3 minutes

### Adding a New Cache Entry

1. **Add to `NAMED_PROJECT_SPECS`** in `tests/cli/conftest.py`:
   ```python
   "base_with_new_service": ProjectTemplateSpec(services=("new_service",)),
   ```

2. **Update tests** to use `project_factory("base_with_new_service")` instead of generating from scratch

3. **Run tests** to verify the cache entry works
