"""The Budget panel's assembly layer: canned API payload in, control
tree out.

The pieces (`compact_budget_row`, `one_time_section`, the toggle) have
their own tests; this drives ``_render`` itself - the wiring that
decides which sections exist. Both recent UI regressions (the one-offs
popup wiring, sections dropped from the page) lived exactly here, in
code no test executed. Payloads come from ``_payloads`` (the real
schemas), so a renamed field breaks these before it breaks the app.
"""

from typing import Any

from tests.components.frontend._payloads import (
    bucket,
    budget_line,
    budget_stats,
    budget_summary,
)
from tests.components.frontend._tree import rendered


def _panel(summary: dict[str, Any]) -> Any:
    from app.components.frontend.dashboard.modals.finance_modal.budget_panel.panel import (
        BudgetPanel,
    )

    panel = BudgetPanel(page=None)  # type: ignore[arg-type]
    panel._summary = summary
    return panel


class TestTheLimitsPage:
    def test_a_flexible_line_reaches_the_page(self) -> None:
        panel = _panel(
            budget_summary(
                buckets=[
                    bucket(
                        "flexible",
                        [budget_line(category_name="Food & Dining:Groceries")],
                    )
                ]
            )
        )
        panel._render()

        page_text = rendered(panel._body.content)
        assert "Food & Dining:Groceries" in page_text

    def test_commitments_hide_behind_the_toggle(self) -> None:
        summary = budget_summary(
            buckets=[
                bucket("flexible", [budget_line()]),
                bucket(
                    "fixed",
                    [budget_line(id=2, category_name="Rent", allocated_amount=185_000)],
                ),
            ]
        )
        panel = _panel(summary)
        panel._render()
        collapsed = rendered(panel._body.content)

        panel._show_commitments = True
        panel._render()
        expanded = rendered(panel._body.content)

        assert "Rent" not in collapsed
        assert "Rent" in expanded
        assert "already committed" in collapsed  # the toggle line stays

    def test_the_one_time_section_appears_only_when_it_has_rows(self) -> None:
        """The section that silently fell off the page once: present with
        a one-off plan, absent - not an empty shell - without one."""
        with_plan = budget_summary(
            buckets=[
                bucket("flexible", [budget_line()]),
                bucket(
                    "one_time",
                    [
                        budget_line(
                            id=3,
                            payee_label="Dentist",
                            allocated_amount=230_000,
                            spent_amount=0,
                            due_date="2026-09-10",
                        )
                    ],
                ),
            ]
        )
        panel = _panel(with_plan)
        panel._show_commitments = True
        panel._render()
        assert "Dentist" in rendered(panel._body.content)

        panel = _panel(budget_summary())
        panel._show_commitments = True
        panel._render()
        assert "One-time" not in rendered(panel._body.content)

    def test_the_stats_strip_reads_the_payload(self) -> None:
        panel = _panel(
            budget_summary(stats=budget_stats(fixed_total=220_000, fixed_count=12))
        )
        panel._render()

        strip = rendered(panel._stats.content)
        assert "$2,200.00" in strip
        assert "12 bills" in strip
