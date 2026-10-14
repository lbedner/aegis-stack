# Database Component

!!! example "Musings: On ORMs and Alternatives (September 2025)"
    I'm well aware of the... disdain... people have for ORMs. SQLModel is the default because it works great for 80% of use cases and integrates beautifully with FastAPI/Pydantic.

    That said, I already have a sub-component feature in the works for folks who prefer raw SQL via driver cursors or SQLAlchemy Core. Choose your own adventure.

Database component with [SQLModel](https://sqlmodel.tiangolo.com/) ORM supporting SQLite and PostgreSQL. PostgreSQL can be self-hosted in a container or run on [Neon](https://neon.tech) serverless Postgres.

Use `aegis init my-project --components database` to include this component. Pick the engine (and, for PostgreSQL, the host) in the interactive prompt, or pass it non-interactively:

```bash
aegis init my-project --components "database[sqlite]"   # file-based (default)
aegis init my-project --components "database[postgres]"  # local postgres container
aegis init my-project --components "database[neon]"      # Neon serverless Postgres
```

Neon is not a separate engine: `database[neon]` is the **postgres** engine hosted on Neon, so every model, migration, and query is identical to a self-hosted postgres stack.

## Database Options

Choose your database based on your deployment needs:

=== "SQLite"

    **File-based • Zero configuration • Development-friendly**

    ```bash
    DATABASE_URL=sqlite:///data/app.db
    ```

    **Perfect for:**

    - Single-container deployments
    - Development and testing
    - Embedded applications
    - Simple deployment requirements

    **Features:**

    - No external dependencies
    - File-based simplicity
    - Zero configuration
    - Automatic directory creation

    **Limitations:**

    - Single-writer constraint
    - Cross-container access challenges
    - Limited concurrency

=== "PostgreSQL"

    **Server-based • Production-ready • High concurrency**

    ```bash
    DATABASE_URL=postgresql://aegis:aegis@postgres:5432/aegis_db
    ```

    **Perfect for:**

    - Multi-container deployments
    - Production environments
    - High concurrency requirements
    - Advanced database features

    **Features:**

    - Client-server architecture
    - Connection pooling
    - Multi-container support
    - Advanced data types (JSONB, arrays)

    **Requirements:**

    - PostgreSQL service (via Docker Compose)
    - Network configuration
    - Credentials management

=== "Neon"

    **Serverless Postgres • No DB container in production • Cloud-hosted**

    ```bash
    # App runtime uses the POOLED endpoint (note the -pooler host)
    DATABASE_URL=postgresql://user:pass@ep-xxxx-pooler.region.aws.neon.tech/dbname
    # Migrations use the DIRECT (unpooled) endpoint
    DATABASE_URL_UNPOOLED=postgresql://user:pass@ep-xxxx.region.aws.neon.tech/dbname
    ```

    **Perfect for:**

    - Serverless and autoscaling deployments
    - Per-PR / preview database branches
    - Teams that would rather not operate a database server

    Neon is the **postgres** engine hosted on Neon's cloud: development
    still runs the local container, production connects to Neon. See the
    [Neon page](database/neon.md) for endpoints, setup, and how the
    generated code adapts at runtime.

## Choosing a Database

### Cross-Container Considerations

**SQLite limitation**: File-based databases can't be shared across containers. If multiple services need database access (e.g., API + Scheduler), you need PostgreSQL.

**PostgreSQL advantage**: Network-based access allows any container to connect, making it ideal for microservice architectures.

### Hosting PostgreSQL: container or Neon

Both `database[postgres]` and `database[neon]` use the same engine; they differ only in where production runs:

- **Container** (`database[postgres]`): a `postgres:16` service runs in your Docker Compose stack in every environment (`make serve`, `make serve-prod`, and `aegis deploy`). You operate and back up the database.
- **Neon** (`database[neon]`): development still runs the local container, but production has no database service, the app connects to Neon's cloud via `DATABASE_URL`, and Neon handles autoscaling, scale-to-zero, and branching.

The generated connection code detects a Neon host (`*.neon.tech`) at runtime and applies Neon's pooler-safe connection settings only then, so one codebase runs against the local container in development and Neon in production. See the [Neon page](database/neon.md) for the full provider guide.

## Common Patterns

### Adding Your First Model

**Step 1: Create Your Model**
```python
# app/models/shield.py
from sqlmodel import SQLModel, Field

class Shield(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    defense_rating: int = Field(default=10)
    material: str = "iron"
    enchantment: str | None = None
```

**Step 2: Use It**
```python
# In your API endpoint
from app.core.db import db_session
from app.models.shield import Shield

@router.post("/shields")
async def forge_shield(shield_data: ShieldCreate):
    with db_session() as session:
        shield = Shield(**shield_data.dict())
        session.add(shield)
        # Automatically committed
    return {"id": shield.id, "name": shield.name}
```

That's it! The database handles persistence automatically.

## Session Management

```python
from app.core.db import db_session

# Auto-commit on success, rollback on error
with db_session() as session:
    shield = Shield(name="Dragon Scale Shield")
    session.add(shield)
    # Automatically committed when context exits
```

## Migrations

Database schema changes are managed with [Alembic](https://alembic.sqlalchemy.org/):

### Generate Migration

```bash
# After creating/modifying models
alembic revision --autogenerate -m "Add shields table"

# Or let the project derive it, the same way `aegis add` does
uv run python -m app.cli.migrate_gen <service>
```

The models are the source of the schema: `aegis init` and `aegis add` derive
every revision they write from the SQLModel classes. To check that nothing has
drifted, replay the revisions onto a scratch database and diff:

```bash
uv run python -m app.cli.migrate_gen --check
```

Empty output means the revisions rebuild the models exactly;
`tests/test_model_registry.py` asserts it on every test run.

### Apply Migrations

```bash
# Apply all pending migrations
make migrate

# Or use alembic directly
alembic upgrade head
```

### Migration Best Practices

- Generate migrations after model changes
- Review auto-generated migrations before applying
- Test migrations in development first
- Commit migrations to version control
- Migrations work identically for SQLite and PostgreSQL
- On Neon, migrations run over the direct (unpooled) `DATABASE_URL_UNPOOLED` endpoint automatically; the pooled endpoint is reserved for app runtime

## Database Activity

A transaction held longer than `DATABASE_SLOW_TRANSACTION_SECONDS` (2 seconds by default), and a statement that found the database locked, are recorded with the process and the line of app code behind each. They show on the Database page's **Activity** tab in the Overseer and the Flet dashboard, and in the log.

On SQLite every write takes the database's one write lock and waits up to 30 seconds for it, so `database is locked` means some other transaction held the lock that long. The Activity tab names it: usually a session kept open across slow work (an LLM call, a provider request, a long stream). The fix stays local: end the transaction before the slow call with `release_lock(session)` from `app.core.db`, or commit sooner.

A request that opens a second transaction while it still holds one waits out those 30 seconds behind itself and then fails. That is recorded the moment it happens, as **Waits on itself**, naming the line that opened the second one: end the first (`release_lock`) before calling code that opens a session of its own.

### Transactions open right now

The Overseer's Database page has a **Transactions** section, live while it is open:

- **PostgreSQL**: every connection to the database (`pg_stat_activity`), the longest open transaction first, with its process (each connection names the process that opened it, such as `worker:268`), its state, how long its transaction has been open, what it is waiting on, which connections block it, and its query. **End** closes one connection and rolls its transaction back (`pg_terminate_backend`); it confirms first, is for admins, and is audited.
- **SQLite**: SQLite cannot say who holds its lock, so each process publishes the transactions it has held for more than a second, with the line of app code holding each right now (what it is waiting on, a model call, say) and the container it runs in. SQLite cannot end another process's transaction, so **Restart** restarts the container holding it.

A transaction open past `DATABASE_SLOW_TRANSACTION_SECONDS` shows red.

Records live for an hour, in Redis when the stack has it (the webserver then shows what the worker and scheduler recorded too), otherwise in the process that recorded them. `DATABASE_SLOW_TRANSACTION_SECONDS=0` turns it off; it is also on the Database page's Settings section and Overseer > Settings. The engine's own parameters (PostgreSQL settings, SQLite PRAGMAs) are the page's **Engine** section.

### A table's rows

The Overseer's Database page has a **Rows** section: pick a table and page through its rows, laid out like Logs across the whole window, one line each (click a row, or **Wrap**, to see it whole). A table name on the **Schema** section leads there too.

- Only a table the app's models declare, and that the database has, can be read.
- It sorts only by a column an index serves (the key, an indexed or unique column), and filters (`column:value`, or several as `column:value, column:value`) by those or a foreign key's columns. A foreign key PostgreSQL has no index for can mean reading the whole table, which the 5-second limit bounds.
- Above the rows, the table's keys: each foreign key out of it and into it, a composite one whole (`note.post_id, tag_id → tagged.post_id, tag_id`). Click a row and, under it, each key leads to the rows it points at or that point at it (a table that points at itself, both ways), refiltering the same scroller to them.
- The default order is the table's key, and the next page starts where the last one ended rather than at an offset, so a deep page costs what the first does. Sorting by another column pages by offset, at most 400 pages deep.
- 25 rows a page. The count shown is the health check's: exact on SQLite, PostgreSQL's estimate otherwise.
- A text column holding a secret (a password hash, a token, a stored secret, an encrypted value) is never read: the database returns it as hidden, and it cannot be sorted or filtered by. Other text is read to 1,024 characters, cleared of anything that looks like a credential (a URL's password, a bearer token), then cut; binary shows its size.
- A read stops after 5 seconds (PostgreSQL's `statement_timeout`; on SQLite, an interrupt), and PostgreSQL reads in a read-only transaction.
- It reads through the app's sync session factory, which never begins a write transaction, so on SQLite reading rows never holds the write lock; the connection has `query_only` on while it reads.
- The rows are the app's data: outside dev they stay hidden until an admin turns on `OVERSEER_DATABASE_ROWS_ENABLED` (Overseer > Settings). With the auth service, Overseer is for admins only; without it, the setting counts only on the build that was never deployed, and the page says to add auth instead.

### A query

The **Query** section runs one SQL statement you type, read-only, and shows its rows in the same scroller.

- A write fails because the connection cannot write, not because the SQL was inspected: PostgreSQL runs it in a read-only transaction, rolled back; SQLite with `query_only` on, and `ATTACH`, `DETACH` and every `PRAGMA` refused, so the statement cannot turn it off. `INSERT`, `UPDATE`, `DELETE`, DDL, and a write inside a CTE or a function all fail.
- One statement at a time: a `;` inside it is refused (a trailing one is fine).
- The first 200 rows, saying so when there were more; it stops after 5 seconds, as a table's rows do.
- A secret never leaves the database. On SQLite, every column the models hold one in reads as empty however the statement reaches it (an alias, a `UNION`, a CTE's column list), and shows as hidden under its own name (`SELECT *`). PostgreSQL cannot blank a column, so a statement whose plan reads a table holding a secret is refused; read that table on **Rows**, where its secrets are hidden. Cells are cleared of credentials and cut, as a table's rows are.
- On PostgreSQL, outside dev, Query refuses a superuser login: a read-only transaction does not stop a superuser's `COPY ... TO PROGRAM` or reads of the server's files. Run the app as a login that is not a superuser to use it there. Each query runs on its own connection, closed after it, so nothing it sets outlives it.
- Every run is recorded in the audit log (`database.query`), refused ones too, with who ran it and the statement.
- It is shown where a table's rows are, and only to someone who may make Overseer's changes: an admin with the auth service; without it, the build that was never deployed, at localhost.

## Testing

The component includes test fixtures for database testing:

```python
# tests/conftest.py provides:
@pytest.fixture
def db_session():
    # Provides isolated test database session
    # Automatically rolls back after each test
```

**Test Infrastructure:**

```bash
# Quick health check
make health-detailed
```

- In-memory test databases
- Transaction rollback patterns
- Isolated test environments
- Same patterns work for both SQLite and PostgreSQL

## Next Steps

- **[SQLModel Documentation](https://sqlmodel.tiangolo.com/)** - Complete ORM capabilities
- **[Component Overview](./index.md)** - Understanding Aegis Stack's component architecture
