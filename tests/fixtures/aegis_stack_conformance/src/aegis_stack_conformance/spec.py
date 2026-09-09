"""A plugin that declares one of everything the install path can wire.

Nothing here is useful at runtime. The point is that every mechanism
``aegis add <plugin>`` is supposed to fire has a visible consequence in
the generated project, so ``tests/cli/test_plugin_conformance.py`` can
assert on it. Three gaps shipped because a mechanism existed for in-tree
services and was never wired for plugins: migrations never ran (#1075),
the cross-spec services card was never restored, and ``auto_requires``
is still never applied (#1079). Each was found by hand, one at a time.
"""

from aegis.core.file_manifest import FileManifest
from aegis.core.migration_spec import ColumnSpec, IndexSpec, MigrationSpec, TableSpec
from aegis.core.option_spec import OptionMode, OptionSpec
from aegis.core.plugins.spec import (
    HealthCheckWiring,
    PluginKind,
    PluginSpec,
    PluginWiring,
    RouterWiring,
    SymbolWiring,
)


def get_spec() -> PluginSpec:
    return PluginSpec(
        name="conformance",
        kind=PluginKind.SERVICE,
        description="Declares one of every plugin mechanism.",
        version="0.0.1",
        verified=False,
        cli_name="conformance",
        required_components=["database"],
        options=[
            # ``objects`` should pull in the storage component the way
            # ``ai[sqlite]`` pulls in a database. It does not today.
            OptionSpec(
                name="bodies",
                mode=OptionMode.SINGLE,
                choices=["column", "objects"],
                default="column",
                answer_key="conformance_bodies",
                auto_requires=lambda v: ["storage"] if v == "objects" else [],
            ),
        ],
        migrations=[
            MigrationSpec(
                service_name="conformance",
                description="Conformance table",
                schema="conformance",
                # Proof it ran, for the startup re-adoption hook.
                stamp_signature=("table", "conformance.conformance_row"),
                tables=[
                    TableSpec(
                        name="conformance_row",
                        columns=[
                            ColumnSpec(
                                "id", "sa.Integer()", nullable=False, primary_key=True
                            ),
                            ColumnSpec("label", "sa.String(length=64)", nullable=False),
                            ColumnSpec(
                                "created_at",
                                "sa.DateTime(timezone=True)",
                                nullable=False,
                            ),
                        ],
                        indexes=[IndexSpec("ix_conformance_row_label", ["label"])],
                    ),
                ],
            ),
        ],
        files=FileManifest(
            primary=["app/services/conformance", "app/cli/conformance.py"]
        ),
        wiring=PluginWiring(
            routers=[
                RouterWiring(
                    module="app.services.conformance.api",
                    symbol="router",
                    prefix="/api/v1/conformance",
                    tags=["conformance"],
                ),
            ],
            settings_mixins=[
                SymbolWiring(
                    module="app.services.conformance.settings",
                    symbol="ConformanceSettingsMixin",
                ),
            ],
            health_checks=[
                HealthCheckWiring(
                    module="app.services.conformance.health",
                    symbol="conformance_health",
                    label="Conformance",
                ),
            ],
        ),
    )
