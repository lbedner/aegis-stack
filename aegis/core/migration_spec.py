"""
Migration spec — plugin-author-facing facade for ``ServiceMigrationSpec``.

``PluginSpec.migrations`` is a list of ``ServiceMigrationSpec`` objects. The
canonical dataclass lives in ``aegis/core/migration_generator.py``; this
module exposes it under a stable import path so plugin authors don't have to
know the historical filename.

A spec does not describe tables. What a revision contains is derived from the
plugin's SQLModel classes, by the generated project's own
``app/cli/migrate_gen.py``, at ``aegis add`` time - so a column exists in one
place, the model. The spec names the revision and carries what models cannot
express: the Postgres schema its tables live in, the object whose existence
proves the migration ran, and any data statement (a row a new foreign key
points at).

Intended usage (in a third-party plugin's ``get_spec()``)::

    from aegis.core.migration_spec import MigrationSpec

    PluginSpec(
        name="scraper",
        ...
        migrations=[
            MigrationSpec(
                service_name="scraper",
                description="Scraper tables",
                schema="scraper",
                stamp_signature=("table", "scraper.scrape_targets"),
            ),
        ],
    )

The plugin's models go under ``app/services/scraper/models`` in its template
tree; the model registry imports that path, and the generator writes the
revision from what it finds.
"""

from collections.abc import Iterable

from .migration_generator import ServiceMigrationSpec

# Plugin-system-shape alias. Same class; preferred name in PluginSpec.migrations.
MigrationSpec = ServiceMigrationSpec


def collect_migrations(
    specs: Iterable[object],
) -> dict[str, ServiceMigrationSpec]:
    """Build the legacy ``MIGRATION_SPECS`` dict from ``PluginSpec.migrations``.

    Iterates an iterable of ``PluginSpec`` objects, flattens each spec's
    ``migrations`` list, and keys the result by ``ServiceMigrationSpec.service_name``
    (matching the pre-R4 dict shape so callers ``add_service.py``,
    ``copier_manager.py``, and the test suite continue to work unchanged).

    Args:
        specs: An iterable of ``PluginSpec``-like objects (anything with a
            ``.migrations`` attribute holding ``ServiceMigrationSpec`` items).
            Typed as ``Iterable[object]`` rather than a concrete protocol so
            duck-typed test fakes / future plugin classes pass without
            inheriting from ``PluginSpec``.

    Returns:
        ``{service_name: ServiceMigrationSpec}`` for every migration declared
        across the iterable.
    """
    out: dict[str, ServiceMigrationSpec] = {}
    for spec in specs:
        for migration in getattr(spec, "migrations", None) or []:
            out[migration.service_name] = migration
    return out


__all__ = [
    "MigrationSpec",
    "ServiceMigrationSpec",
    "collect_migrations",
]
