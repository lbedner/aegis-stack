"""What the database detail views show, for every frontend.

Read from the database health check's metadata and returned as display
strings, so the Flet modal and the web Overseer render the same values from
one place. No UI framework imports.
"""

from datetime import datetime
import re
from typing import Any

from app.core import credential
from app.core.formatting import format_relative_time

# Docker service names a developer reaches as localhost from the host.
_DOCKER_HOSTS = ("@db:", "@postgres:", "@postgresql:", "@database:", "@redis:")

_TEMP_STORE = {0: "DEFAULT", 1: "FILE", 2: "MEMORY"}
_SYNCHRONOUS = {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}
_AUTO_VACUUM = {0: "NONE", 1: "FULL", 2: "INCREMENTAL"}


def is_postgres(metadata: dict[str, Any]) -> bool:
    return metadata.get("implementation", "sqlite") == "postgresql"


def display_url(url: str, hide_password: bool = True) -> str:
    """The URL as a developer on the host would use it.

    Docker service hosts become localhost. The password is hidden unless the
    caller keeps it for a copy-to-clipboard action.
    """
    for host in _DOCKER_HOSTS:
        url = url.replace(host, "@localhost:")
    return credential.hide_password(url) if hide_password else url


def overview(metadata: dict[str, Any]) -> dict[str, str]:
    """Headline figures and statistics for the Overview tab."""
    if is_postgres(metadata):
        size = str(metadata.get("database_size_human", "Unknown"))
        max_connections = (metadata.get("pg_settings") or {}).get(
            "max_connections", "?"
        )
        connections = f"{metadata.get('active_connections', 0)} / {max_connections}"
    else:
        size = str(metadata.get("file_size_human", "0 B"))
        connections = str(metadata.get("connection_pool_size", 1))
    largest = metadata.get("largest_table") or {}
    return {
        "tables": str(metadata.get("table_count", 0)),
        "rows": f"{metadata.get('total_rows', 0):,}",
        "size": size,
        "connections": connections,
        "pool_size": str(metadata.get("connection_pool_size", 0)),
        "indexes": str(metadata.get("total_indexes", 0)),
        "foreign_keys": str(metadata.get("total_foreign_keys", 0)),
        "largest": f"{largest.get('name', 'None')} ({largest.get('rows', 0):,} rows)",
    }


def create_table_sql(table: dict[str, Any]) -> str:
    """A table's schema as a CREATE TABLE statement, indexes and FKs after."""
    name = table.get("name", "Unknown")
    definitions = []
    primary = []
    for column in table.get("columns") or []:
        definition = f"    {column.get('name', '?')} {column.get('type', '?')}"
        if not column.get("nullable", True):
            definition += " NOT NULL"
        definitions.append(definition)
        if column.get("primary_key"):
            primary.append(column.get("name", "?"))
    if primary:
        definitions.append(f"    PRIMARY KEY ({', '.join(primary)})")
    body = [",\n".join(definitions)] if definitions else []
    lines = [f"CREATE TABLE IF NOT EXISTS {name} (", *body, ");"]
    if indexes := table.get("indexes"):
        lines += ["", "-- Indexes"]
        for index in indexes:
            unique = "UNIQUE " if index.get("unique") else ""
            columns = ", ".join(index.get("columns") or [])
            lines.append(
                f"CREATE {unique}INDEX {index.get('name', '?')} ON {name} ({columns});"
            )
    if foreign_keys := table.get("foreign_keys"):
        lines += ["", "-- Foreign Keys"]
        for fk in foreign_keys:
            lines.append(
                f"-- {fk.get('column', '?')} REFERENCES "
                f"{fk.get('referred_table', '?')}({fk.get('referred_column', '?')})"
            )
    return "\n".join(lines)


def tables(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per table for the Schema tab, with its CREATE statement."""
    return [
        {
            "name": table.get("name", "Unknown"),
            "rows": table.get("rows", 0),
            "columns": len(table.get("columns") or []),
            "indexes": len(table.get("indexes") or []),
            "foreign_keys": len(table.get("foreign_keys") or []),
            "sql": create_table_sql(table),
        }
        for table in metadata.get("table_schemas") or []
    ]


def _migration_date(mtime: Any) -> str:
    try:
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError, TypeError):
        return "Unknown"


def migrations(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per migration for the Migrations tab, with its source."""
    rows = []
    for migration in metadata.get("migrations") or []:
        revision = str(migration.get("revision", "Unknown"))[:12]
        current = bool(migration.get("is_current"))
        content = migration.get("content") or "# Migration content not available"
        rows.append(
            {
                "revision": f"{revision} (current)" if current else revision,
                "current": current,
                "date": _migration_date(migration.get("file_mtime")),
                "description": migration.get("description", "No description"),
                "file_path": migration.get("file_path", "Unknown"),
                "content": re.sub(r"\n\s*\n", "\n", content),
            }
        )
    return rows


def _setting_value(value: Any) -> str:
    if isinstance(value, bool):
        return "Enabled" if value else "Disabled"
    if isinstance(value, int | float):
        return f"{value:,}"
    return str(value)


def _postgres_settings(metadata: dict[str, Any]) -> list[tuple[str, Any, str]]:
    pg = metadata.get("pg_settings") or {}
    rows: list[tuple[str, Any, str]] = []
    if "max_connections" in pg:
        rows.append(("max_connections", pg["max_connections"], "Connections"))
    rows.append(
        (
            "active_connections",
            str(metadata.get("active_connections", 0)),
            "Connections",
        )
    )
    for key in (
        "shared_buffers",
        "work_mem",
        "effective_cache_size",
        "maintenance_work_mem",
    ):
        if key in pg:
            rows.append((key, pg[key], "Memory"))
    if "wal_level" in pg:
        rows.append(("wal_level", pg["wal_level"], "WAL"))
    return rows


def _sqlite_settings(metadata: dict[str, Any]) -> list[tuple[str, Any, str]]:
    pragma = {
        **(metadata.get("pragma_settings") or {}),
        **(metadata.get("comprehensive_pragma") or {}),
    }
    shown: dict[str, Any] = {
        "temp_store": _TEMP_STORE.get(
            pragma.get("temp_store", -1), pragma.get("temp_store")
        ),
        "busy_timeout": f"{pragma.get('busy_timeout')}ms",
        "synchronous": _SYNCHRONOUS.get(
            pragma.get("synchronous", -1), pragma.get("synchronous")
        ),
        "auto_vacuum": _AUTO_VACUUM.get(
            pragma.get("auto_vacuum", -1), pragma.get("auto_vacuum")
        ),
        "journal_mode": str(pragma.get("journal_mode", "")).upper(),
        "page_size": f"{pragma.get('page_size')} bytes",
        "db_efficiency": f"{pragma.get('db_efficiency', 0):.2f}%",
    }
    layout = [
        ("cache_size", "Performance"),
        ("mmap_size", "Performance"),
        ("temp_store", "Performance"),
        ("busy_timeout", "Performance"),
        ("foreign_keys", "Integrity"),
        ("synchronous", "Integrity"),
        ("auto_vacuum", "Integrity"),
        ("journal_mode", "Storage"),
        ("wal_enabled", "Storage"),
        ("page_size", "Storage"),
        ("page_count", "Statistics"),
        ("freelist_count", "Statistics"),
        ("db_efficiency", "Statistics"),
    ]
    pragma["wal_enabled"] = bool(metadata.get("wal_enabled", False))
    return [
        (key, shown.get(key, pragma[key]), category)
        for key, category in layout
        if key in pragma
    ]


def activity(metadata: dict[str, Any]) -> list[dict[str, str]]:
    """Slow transactions and lock failures (``app.core.db_activity``),
    newest first, for the Activity tab."""
    return [
        {
            "when": format_relative_time(event["at"]),
            "what": "Locked"
            if event["kind"] == "locked"
            else f"Held {event['seconds']} s",
            "process": event["process"],
            "caller": event["caller"],
        }
        for event in metadata.get("activity", [])
    ]


def settings(metadata: dict[str, Any]) -> list[dict[str, str]]:
    """Server settings (PostgreSQL) or PRAGMAs (SQLite) for the Settings tab."""
    rows = (
        _postgres_settings(metadata)
        if is_postgres(metadata)
        else _sqlite_settings(metadata)
    )
    return [
        {"setting": name, "value": _setting_value(value), "category": category}
        for name, value, category in rows
    ]
