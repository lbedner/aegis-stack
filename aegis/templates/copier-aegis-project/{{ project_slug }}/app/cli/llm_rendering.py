"""Rich renderings for the ``llm`` commands.

Catalog statistics and sync results, as tables and panels. Lifted
out of ``llm.py`` so the commands module stays commands.
"""

from rich.table import Table

from app.cli import theme
from app.i18n import t
from app.services.ai.domains.llm.etl import CatalogStats, SyncResult

console = theme.console()


def _display_catalog_stats(stats: CatalogStats) -> None:
    """Display catalog statistics in formatted tables.

    Args:
        stats: The catalog stats to display.
    """
    # Summary table
    summary_table = Table(title=t("llm.catalog_summary"))
    summary_table.add_column(t("llm.metric_column"), style="dim")
    summary_table.add_column(t("llm.count_column"), justify="right")

    summary_table.add_row(t("llm.vendors_row"), str(stats.vendor_count))
    summary_table.add_row(t("llm.models_row"), str(stats.model_count))
    summary_table.add_row(t("llm.deployments_row"), str(stats.deployment_count))
    summary_table.add_row(t("llm.prices_row"), str(stats.price_count))

    console.print(summary_table)
    console.print()

    # Top vendors table
    if stats.top_vendors:
        vendor_table = Table(title=t("llm.top_vendors"))
        vendor_table.add_column(t("llm.vendor_column"), style=theme.ACCENT)
        vendor_table.add_column(t("llm.models_column"), justify="right")

        for vendor_name, count in stats.top_vendors:
            vendor_table.add_row(vendor_name, str(count))

        console.print(vendor_table)


def _display_sync_result(result: SyncResult, dry_run: bool, duration: float) -> None:
    """Display sync results in a formatted table.

    Args:
        result: The sync result to display.
        dry_run: Whether this was a dry run.
        duration: How long the sync took in seconds.
    """
    title = t("llm.sync_results_dry_run") if dry_run else t("llm.sync_results")
    table = Table(title=title)
    table.add_column(t("llm.metric_column"), style="dim")
    table.add_column(t("llm.count_column"), justify="right")

    table.add_row(t("llm.vendors_added"), str(result.vendors_added))
    table.add_row(t("llm.vendors_updated"), str(result.vendors_updated))
    table.add_row(t("llm.models_added"), str(result.models_added))
    table.add_row(t("llm.models_updated"), str(result.models_updated))
    table.add_row(t("llm.deployments_synced"), str(result.deployments_synced))
    table.add_row(t("llm.prices_synced"), str(result.prices_synced))
    table.add_row(t("llm.modalities_synced"), str(result.modalities_synced))
    table.add_row(t("llm.duration_row"), f"{duration:.2f}s")

    if result.errors:
        table.add_row(t("llm.errors_row"), f"[{theme.ERROR}]{len(result.errors)}[/]")

    console.print(table)

    if result.errors:
        console.print(f"\n[{theme.ERROR}]{t('llm.errors_header')}[/]")
        for error in result.errors[:10]:  # Show first 10 errors
            console.print(f"  \u2022 {error}")
        if len(result.errors) > 10:
            console.print(
                f"  {t('llm.and_more_errors', count=len(result.errors) - 10)}"
            )
