"""Module size budget for the generated project.

The reader this protects is an agent. A file is the unit it loads, greps and
edits: 500 lines of this codebase is roughly 7k tokens, so ten of them fit in
a working window alongside everything else. A 2,000-line file eats a fifth of
that window by itself and pushes past the Read tool's default window, which
turns "read the file" into "page the file" - and paging is where whole-file
reasoning starts making mistakes.

Three rules, because one number cannot express the shape:

* **Logic modules cap at 500 lines.** Absolute size is what an agent pays for;
  a ratio alone would let a three-file package sit at 1,000 lines each.
* **Declaration modules get 900.** Models, schemas, locale catalogs and seed
  fixtures are lists, not arguments. Nobody reads them end to end - they get
  grepped for one name - so length costs far less.
* **No module may exceed 40% of its package AND 400 lines.** This is what the
  cap cannot see: one fat module surrounded by stubs passes any per-file limit
  while still being the thing everyone opens. Both halves are needed - 49% of
  a 759-line package is a normal shape, 72% of a 1,200-line one is a god
  module wearing a folder.

BUDGET is a RATCHET, not an allowlist. Each entry records the file's size when
it was measured; the test fails if a file grows past its own entry. So
existing debt does not block work, nothing gets worse, and anything new must
meet the budget outright. Shrink a file below its limit and the last test
tells you to delete its line.
"""

from __future__ import annotations

import collections
from pathlib import Path

TEMPLATE_APP = (
    Path(__file__).parent.parent.parent
    / "aegis/templates/copier-aegis-project/{{ project_slug }}/app"
)

LOGIC_LIMIT = 500
DECLARATION_LIMIT = 900
PACKAGE_SHARE_LIMIT = 0.40
# A share only means something when the file is substantial on its own.
PACKAGE_SHARE_MIN_LINES = 400

# Lists rather than logic: read by grep, never end to end.
DECLARATION_PARTS = ("models", "schemas", "i18n", "seeds", "fixtures", "locales")

# path -> line count when recorded. The refactoring backlog, largest first.
BUDGET: dict[str, int] = {
    "components/frontend/dashboard/modals/finance_modal/budget_panel/panel.py": 552,
    "components/frontend/dashboard/modals/finance_modal/transactions_panel/panel.py": 903,
    "components/frontend/dashboard/modals/finance_modal/transactions_panel/declare.py": 586,
    "components/frontend/dashboard/modals/finance_modal/uncategorized_panel.py": 850,
    "components/frontend/dashboard/modals/finance_modal/no_payee_panel.py": 668,
    "components/frontend/dashboard/modals/finance_modal/overview_tab.py": 749,
    "components/frontend/dashboard/modals/finance_modal/budget_cards.py": 681,
    "components/frontend/dashboard/modals/insights_modal.py": 3940,
    "services/system/health.py.jinja": 2413,
    "cli/ai.py.jinja": 2338,
    "components/frontend/dashboard/modals/modal_sections.py": 2093,
    "components/frontend/dashboard/modals/voice_settings_tab.py": 1649,
    "services/payment/payment_service.py.jinja": 1631,
    "services/insights/view_service.py": 1575,
    "components/frontend/dashboard/modals/blog_modal.py": 1454,
    "components/frontend/main.py.jinja": 1423,
    "components/frontend/dashboard/modals/worker_modal.py": 1351,
    "i18n/locales/en.py": 1301,
    "i18n/locales/zh.py": 1277,
    "i18n/locales/de.py": 1247,
    "i18n/locales/es.py": 1247,
    "i18n/locales/fr.py": 1247,
    "i18n/locales/ja.py": 1247,
    "i18n/locales/ru.py": 1247,
    "i18n/locales/ko.py": 1246,
    "components/frontend/dashboard/modals/backend_modal.py": 1244,
    "i18n/locales/zh_hant.py": 1243,
    "services/finance/adapters/importers/imports.py": 1189,
    "components/frontend/dashboard/modals/ollama_modal.py": 1202,
    "components/frontend/dashboard/modals/payment_modal.py": 1111,
    "components/frontend/controls/data_table.py": 1089,
    "services/finance/adapters/providers/connections/plaid_sync.py": 1024,
    "services/finance/seeds/demo_seed.py": 1075,
    "components/backend/api/ai/router.py.jinja": 1009,
    "cli/payment.py.jinja": 917,
    "services/ai/domains/llm/etl/llm_sync_service.py": 793,
    "services/ai/domains/llm/providers.py.jinja": 980,
    "components/backend/api/auth/router.py.jinja": 881,
    "services/finance/domains/detection/insights/rules.py": 944,
    "components/frontend/dashboard/modals/comms_modal.py": 831,
    "components/frontend/controls/form_fields.py": 817,
    "cli/load_test.py.jinja": 797,
    "cli/blog.py.jinja": 795,
    "services/auth/user_service.py.jinja": 782,
    "components/frontend/dashboard/modals/llm_catalog_tab.py.jinja": 780,
    "components/frontend/dashboard/modals/rag_tab.py": 780,
    "components/frontend/dashboard/cards/card_utils.py.jinja": 659,
    "core/config.py.jinja": 764,
    "cli/rag.py": 686,
    "services/ai/fixtures/llm_fixtures.py": 684,
    "services/load_test/worker/service.py": 678,
    "components/backend/startup/component_health.py.jinja": 690,
    "components/frontend/dashboard/modals/observability_modal.py": 659,
    "services/load_test/worker/service_dramatiq.py": 659,
    "components/frontend/dashboard/modals/database_modal.py": 656,
    "cli/health.py.jinja": 652,
    "services/load_test/worker/service_taskiq.py": 651,
    "components/frontend/dashboard/modals/redis_modal.py": 644,
    "components/frontend/controls/pickers.py": 629,
    "services/finance/domains/detection/recurring/detect.py": 615,
    "services/blog/blog_service.py": 598,
    "services/ai/domains/chat/health_context.py": 596,
    "services/finance/domains/planning/budgets/summary.py": 595,
    "cli/api_load_test.py": 592,
    "components/frontend/dashboard/modals/finance_payees_tab.py": 581,
    "cli/slash_commands.py.jinja": 579,
    "services/finance/domains/planning/goals.py": 575,
    "components/frontend/theme.py": 572,
    "components/frontend/dashboard/activity_feed.py": 572,
    "components/worker/task_history.py": 569,
    "components/scheduler/main.py.jinja": 561,
    "services/system/health_db_sqlite.py.jinja": 559,
    "cli/finance.py.jinja": 551,
    "services/rag/vectorstore.py": 538,
    "cli/marko_terminal_renderer.py": 535,
    "components/backend/api/orgs/router.py.jinja": 534,
    "services/finance/domains/ledger/networth.py": 531,
    "components/frontend/dashboard/modals/ai_analytics_tab.py": 530,
    "components/backend/api/worker.py.jinja": 528,
    "components/frontend/dashboard/modals/auth_users_tab.py.jinja": 521,
    "services/finance/domains/detection/transfers.py": 520,
    "cli/llm.py": 512,
    "services/system/health_db_postgres.py.jinja": 503,
    "services/ai/domains/voice/stt/providers.py": 491,
    "services/load_test_workloads.py": 456,
    "components/backend/api/payment/router.py.jinja": 428,
    "services/finance/domains/investments/securities.py": 426,
}


def _is_declaration(rel: str) -> bool:
    return any(part in rel.split("/") or part in rel for part in DECLARATION_PARTS)


def _limit_for(rel: str) -> int:
    return DECLARATION_LIMIT if _is_declaration(rel) else LOGIC_LIMIT


def _python_files() -> dict[str, int]:
    return {
        str(p.relative_to(TEMPLATE_APP)): len(p.read_text().splitlines())
        for p in TEMPLATE_APP.rglob("*")
        if p.suffix in (".py", ".jinja") and "__pycache__" not in str(p)
    }


def test_no_module_exceeds_its_line_budget() -> None:
    over = []
    for rel, lines in sorted(_python_files().items()):
        limit = BUDGET.get(rel) or _limit_for(rel)
        if lines > limit:
            how = "over its recorded size" if rel in BUDGET else "over budget"
            over.append(f"{rel}: {lines} lines, {how} ({limit})")
    assert not over, "Split these, or the budget is a suggestion:\n  " + "\n  ".join(
        over
    )


def test_no_module_dominates_its_package() -> None:
    dominant = [
        rel for rel in sorted(_dominant_modules(_python_files())) if rel not in BUDGET
    ]
    assert not dominant, (
        "These packages are one file wearing a folder:\n  " + "\n  ".join(dominant)
    )


def _dominant_modules(sizes: dict[str, int]) -> set[str]:
    """Paths that are both >40% of their package and substantial on their own."""
    by_package: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
    for rel, lines in sizes.items():
        by_package[str(Path(rel).parent)].append((lines, rel))
    found: set[str] = set()
    for members in by_package.values():
        total = sum(n for n, _ in members)
        if len(members) < 3 or total < 400:
            continue
        lines, rel = max(members)
        if lines / total > PACKAGE_SHARE_LIMIT and lines > PACKAGE_SHARE_MIN_LINES:
            found.add(rel)
    return found


def test_the_backlog_has_no_dead_entries() -> None:
    """A file that got fixed must leave the list, or the next regression hides
    behind a stale allowance. An entry earns its place by still failing one of
    the two rules - the line cap OR the package share."""
    sizes = _python_files()
    dominant = _dominant_modules(sizes)
    stale = [
        f"{rel} ({sizes.get(rel, 0)} lines, limit {_limit_for(rel)})"
        for rel in sorted(BUDGET)
        if rel not in sizes or (sizes[rel] <= _limit_for(rel) and rel not in dominant)
    ]
    assert not stale, "Under budget now - remove from BUDGET:\n  " + "\n  ".join(stale)
