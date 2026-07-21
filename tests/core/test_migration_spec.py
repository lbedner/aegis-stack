"""
Tests for the migration spec facade (R4-A of plugin refactor).

These tests lock in:

* the ``aegis.core.migration_spec`` re-exports work as a stable plugin
  author-facing import path;
* ``collect_migrations()`` produces the same dict shape as the pre-R4
  ``MIGRATION_SPECS`` literal;
* the migration registry is now derived from ``PluginSpec.migrations``
  on every in-tree service, so adding a new in-tree migration in the
  future requires touching only ``services.py``.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from aegis.core.migration_spec import (
    MigrationSpec,
    ServiceMigrationSpec,
    TableSpec,
    collect_migrations,
)
from aegis.core.services import SERVICES


@dataclass
class _FakeSpec:
    """Minimal stand-in for ``PluginSpec`` — name + migrations only."""

    name: str
    migrations: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------------
# Plugin-author-facing facade
# ---------------------------------------------------------------------


class TestFacade:
    def test_migration_spec_is_alias_of_service_migration_spec(self) -> None:
        """``MigrationSpec`` is the same class as ``ServiceMigrationSpec``."""
        assert MigrationSpec is ServiceMigrationSpec

    def test_re_exports_table_helpers(self) -> None:
        """Plugin authors can import the spec helpers from one module."""
        from aegis.core.migration_spec import (
            AlterTableSpec,
            CheckConstraintSpec,
            ColumnSpec,
            ForeignKeySpec,
            IndexSpec,
        )

        # All present and constructible.
        assert AlterTableSpec(name="x") is not None
        assert CheckConstraintSpec(name="c", sqltext="1=1") is not None
        assert ColumnSpec(name="id", type="sa.Integer()") is not None
        assert (
            ForeignKeySpec(columns=["u"], ref_table="user", ref_columns=["id"])
            is not None
        )
        assert IndexSpec(name="ix", columns=["a"]) is not None


# ---------------------------------------------------------------------
# collect_migrations reducer
# ---------------------------------------------------------------------


class TestCollectMigrations:
    def test_empty_iter_returns_empty_dict(self) -> None:
        assert collect_migrations([]) == {}

    def test_spec_without_migrations_yields_nothing(self) -> None:
        assert collect_migrations([_FakeSpec(name="x")]) == {}

    def test_single_migration(self) -> None:
        m = ServiceMigrationSpec(
            service_name="scraper",
            description="Scraper",
            tables=[],
        )
        result = collect_migrations([_FakeSpec(name="scraper", migrations=[m])])
        assert result == {"scraper": m}

    def test_multiple_migrations_per_spec(self) -> None:
        """A single spec may contribute multiple migrations (e.g. auth has
        4: auth, auth_rbac, auth_org, auth_tokens)."""
        m1 = ServiceMigrationSpec(service_name="auth", description="", tables=[])
        m2 = ServiceMigrationSpec(service_name="auth_rbac", description="", tables=[])
        m3 = ServiceMigrationSpec(service_name="auth_org", description="", tables=[])
        result = collect_migrations([_FakeSpec(name="auth", migrations=[m1, m2, m3])])
        assert set(result.keys()) == {"auth", "auth_rbac", "auth_org"}

    def test_keys_use_service_name_not_spec_name(self) -> None:
        """``MIGRATION_SPECS`` is keyed by ``ServiceMigrationSpec.service_name``,
        which can differ from the parent ``PluginSpec.name`` (auth_rbac is
        a sub-feature of the auth spec)."""
        m = ServiceMigrationSpec(service_name="auth_rbac", description="", tables=[])
        result = collect_migrations([_FakeSpec(name="auth", migrations=[m])])
        assert "auth_rbac" in result
        assert "auth" not in result


# ---------------------------------------------------------------------
# MIGRATION_SPECS lazy access (back-compat)
# ---------------------------------------------------------------------


class TestMigrationSpecsLazy:
    def test_module_level_attribute_works(self) -> None:
        """``from aegis.core.migration_generator import MIGRATION_SPECS``
        still works; it's a derived dict now, not a literal."""
        from aegis.core.migration_generator import MIGRATION_SPECS

        assert isinstance(MIGRATION_SPECS, dict)
        assert "auth" in MIGRATION_SPECS

    def test_unknown_attribute_raises(self) -> None:
        """The lazy ``__getattr__`` only resolves ``MIGRATION_SPECS``."""
        import aegis.core.migration_generator as gen

        with pytest.raises(AttributeError):
            gen.NOT_A_REAL_ATTR  # noqa: B018


# ---------------------------------------------------------------------
# Registry-shape sanity
# ---------------------------------------------------------------------


class TestInTreeRegistry:
    """The pre-R4 MIGRATION_SPECS literal had 10 entries. #660 originally
    added ``insights_auth_link`` and ``insights_projects`` as separate
    layered migrations; both have since been folded back into a single
    context-aware ``insights`` spec, so the canonical key set is:

      auth, auth_rbac, auth_org, auth_tokens, ai, ai_voice,
      payment, payment_auth_link, insights, blog.

    R4-A derives the same set from ``SERVICES``. These tests guard
    that mapping so a future spec edit can't silently lose a migration.
    """

    def test_all_legacy_keys_present(self) -> None:
        result = collect_migrations(SERVICES.values())
        assert set(result.keys()) == {
            "auth",
            "auth_rbac",
            "auth_org",
            "auth_tokens",
            "ai",
            "ai_agents",
            "ai_knowledge",
            "ai_sentiment",
            "ai_voice",
            "payment",
            "payment_auth_link",
            "insights",
            "blog",
            "finance",
            "finance_auth_link",
        }

    def test_each_migration_is_a_servicemigrationspec(self) -> None:
        for name, m in collect_migrations(SERVICES.values()).items():
            assert isinstance(m, ServiceMigrationSpec), name
            assert m.service_name == name, (
                f"key {name!r} should match service_name; "
                f"got service_name={m.service_name!r}"
            )

    def test_auth_migration_has_user_table(self) -> None:
        """Smoke check that the table data round-trips through the new path."""
        result = collect_migrations(SERVICES.values())
        user_table = next((t for t in result["auth"].tables if t.name == "user"), None)
        assert isinstance(user_table, TableSpec)
        # Make sure key columns survived.
        col_names = {c.name for c in user_table.columns}
        assert {"id", "email", "hashed_password"}.issubset(col_names)
