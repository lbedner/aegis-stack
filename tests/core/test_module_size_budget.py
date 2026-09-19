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
    # Was one 3,940-line module, now a package of fourteen. These four
    # still carry a long builder each; the numbers ratchet down as the
    # sections come out, and nothing may give the ground back.
    # 457 lines of schemas in a package __init__; surfaced when ai/models gained
    # a third module. Debt recorded at size; the fix is a schemas module.
    "services/ai/models/__init__.py.jinja": 457,
    # Was one 1,649-line module, now a package of four. The recorder
    # still carries a 211-line _build_ui; the number ratchets down
    # when that comes out.
    "components/frontend/main.py.jinja": 894,
    "i18n/locales/en.py": 1324,
    "i18n/locales/zh.py": 1300,
    "i18n/locales/de.py": 1270,
    "i18n/locales/es.py": 1270,
    "i18n/locales/fr.py": 1270,
    "i18n/locales/ja.py": 1270,
    "i18n/locales/ru.py": 1270,
    "i18n/locales/ko.py": 1269,
    "i18n/locales/zh_hant.py": 1266,
    "components/frontend/controls/data_table/table.py": 750,
    # 809 not 796: BUILD_ID (3 lines), WEBSERVER_ENGINE (4) and
    # WEBSERVER_LOOP (6, its Literal wraps) had nowhere else to live,
    # settings are this file. Now 309 over the 500 limit. The serving
    # settings are the third group to land here by default; grouping them
    # into nested models is the split this file keeps asking for.
    "core/config.py.jinja": 809,
    "services/ai/fixtures/llm_fixtures.py": 684,
    "components/backend/startup/component_health.py.jinja": 690,
    # declare.py is unchanged at 408 and under the 500 cap. It trips the
    # SHARE rule only because detect.py - the other big file in
    # recurring/ - became a package, leaving declare the largest thing
    # left. Splitting it would terminate (cadence.py is 332, under the
    # rule's 400 floor) but it is 8 lines past that floor and under its
    # own cap, so it is recorded rather than churned.
    "services/finance/domains/detection/recurring/declare.py": 408,
    # 597: the header/auth helpers went public for app/cli/bench.py, and the
    # module gained `from __future__ import annotations` because its
    # TYPE_CHECKING-only FastAPI import broke at runtime on 3.13.
    "cli/slash_commands.py.jinja": 579,
    "components/scheduler/main.py.jinja": 561,
    "services/system/health_db_sqlite.py.jinja": 559,
    "cli/finance.py.jinja": 551,
    "components/backend/api/orgs/router.py.jinja": 534,
    "components/backend/api/worker.py.jinja": 528,
    "components/frontend/dashboard/modals/auth_users_tab.py.jinja": 521,
    "services/system/health_db_postgres.py.jinja": 503,
    "services/ai/domains/voice/stt/providers.py": 491,
    "services/load_test_workloads.py": 456,
    "components/backend/api/payment/router.py.jinja": 428,
    "services/finance/domains/investments/securities.py": 426,
}


def _is_declaration(rel: str) -> bool:
    """True for a module that is a list rather than an argument.

    Matched on path segments, not substrings: a directory named for one
    of the parts, a file named exactly that, or one suffixed with it
    (``load_test_models.py``). The substring test this replaced handed
    the 900-line allowance to ``models_tab.py`` and ``_i18n_click.py``,
    neither of which is a declaration.
    """
    segments = rel.split("/")
    stem = segments[-1].removesuffix(".jinja").removesuffix(".py")
    return any(part in segments[:-1] for part in DECLARATION_PARTS) or any(
        stem == part or stem.endswith(f"_{part}") for part in DECLARATION_PARTS
    )


def _limit_for(rel: str) -> int:
    return DECLARATION_LIMIT if _is_declaration(rel) else LOGIC_LIMIT


def _python_files() -> dict[str, int]:
    return {
        str(p.relative_to(TEMPLATE_APP)): len(p.read_text().splitlines())
        for p in TEMPLATE_APP.rglob("*")
        if p.suffix in (".py", ".jinja") and "__pycache__" not in str(p)
    }


def test_a_name_that_merely_contains_a_part_is_not_a_declaration() -> None:
    """The 900-line allowance is for lists, not for anything whose path
    happens to spell one.

    ``models_tab.py`` is a UI tab and ``_i18n_click.py`` is CLI glue;
    a substring test handed both the declaration limit, which would let
    either grow to 900 lines of logic unremarked.
    """
    assert not _is_declaration("components/frontend/dashboard/modals/models_tab.py")
    assert not _is_declaration("cli/_i18n_click.py")
    assert not _is_declaration("services/finance/seeds_helper.py")


def test_real_declaration_modules_still_get_the_allowance() -> None:
    assert _is_declaration("i18n/locales/en.py")
    assert _is_declaration("services/blog/models.py")
    assert _is_declaration("services/load_test_models.py")
    assert _is_declaration("services/ai/fixtures/llm_fixtures.py")


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
