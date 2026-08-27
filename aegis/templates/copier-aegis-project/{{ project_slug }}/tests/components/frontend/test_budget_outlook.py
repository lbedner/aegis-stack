"""The Budget header: bills, budget, income, and the month's verdict.

The old strip led with flexible-spending percentages and an "On track"
count - process numbers. The question the tab exists to answer is "do
these settings clear the month", and that needs exactly four figures:
what comes in, what the bills take, what the budgets take, and the
signed remainder.
"""

from app.components.frontend.dashboard.modals.finance_modal import (
    budget_stats_cells,
    outlook_chip,
    outlook_month_label,
    outlook_stats_cells,
)
from app.components.frontend.theme import AegisTheme as Theme

STATS = {
    "income_total": 500_000,
    "income_count": 3,
    "fixed_total": 220_000,
    "fixed_count": 12,
    "flexible_spent": 40_000,
    "flexible_allocated": 150_000,
    "flexible_count": 5,
    "days_left_in_period": 12,
    "month_net": 130_000,
    "trim_residual": 0,
}


class TestTheCells:
    def test_the_four_questions_in_order(self) -> None:
        labels = [c[0] for c in budget_stats_cells(STATS)]
        assert labels == ["Income", "Bills", "Budgets", "This month"]

    def test_bills_carry_their_count_and_money(self) -> None:
        cells = {c[0]: c for c in budget_stats_cells(STATS)}
        _label, value, caption, _color = cells["Bills"]
        assert value == "$2,200.00"
        assert "12 bills" in caption

    def test_budgets_show_spent_against_allocated(self) -> None:
        cells = {c[0]: c for c in budget_stats_cells(STATS)}
        _label, value, caption, _color = cells["Budgets"]
        assert value == "$1,500.00"
        assert "$400.00 spent" in caption

    def test_a_positive_month_wears_the_accent(self) -> None:
        """The verdict is the one cell allowed a colour in both directions:
        red when short, teal when clear - the month's answer, not decoration."""
        cells = {c[0]: c for c in budget_stats_cells(STATS)}
        _label, value, _caption, color = cells["This month"]
        assert value == "+$1,300.00"
        assert color == Theme.Colors.ACCENT

    def test_a_negative_month_is_red_and_says_so(self) -> None:
        stats = {**STATS, "month_net": -50_000}
        cells = {c[0]: c for c in budget_stats_cells(stats)}
        _label, value, caption, color = cells["This month"]
        assert value == "-$500.00"
        assert color == Theme.Colors.ERROR
        assert "short" in caption.lower()

    def test_the_residual_names_the_part_budgets_cannot_fix(self) -> None:
        stats = {**STATS, "month_net": -80_000, "trim_residual": 30_000}
        cells = {c[0]: c for c in budget_stats_cells(stats)}
        _label, _value, caption, _color = cells["This month"]
        assert "$300.00" in caption

    def test_the_process_stats_are_retired(self) -> None:
        labels = [c[0] for c in budget_stats_cells(STATS)]
        assert "On track" not in labels
        assert "Over budget" not in labels
        assert "Flexible spending" not in labels


class TestTheWiring:
    def test_the_panel_renders_these_cells(self) -> None:
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.BudgetPanel._stats_strip)
        assert "budget_stats_cells(" in source

    def test_a_line_amount_opens_the_edit_dialog(self) -> None:
        """Budgets are adjustable in place - that is the whole "tune it
        and watch the month react" loop."""
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.BudgetPanel._line_row)
        assert "_open_edit_limit" in source

    def test_a_negative_month_offers_its_trims(self) -> None:
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.BudgetPanel)
        assert "_trims_section" in source
        assert "trims" in source


class TestGoalsInTheStrip:
    """GL-04: active goals' ask rides the Budgets cell as a caption line
    - no fifth cell, the strip is already width-tight at four."""

    def test_goals_join_the_budgets_caption(self) -> None:
        cells = budget_stats_cells({**STATS, "goals_total": 75_000, "goals_count": 2})
        budgets = next(c for c in cells if c[0] == "Budgets")
        assert "+ $750.00 to goals" in budgets[2]

    def test_no_goals_no_caption_noise(self) -> None:
        for stats in (STATS, {**STATS, "goals_total": 0, "goals_count": 0}):
            budgets = next(c for c in budget_stats_cells(stats) if c[0] == "Budgets")
            assert "goals" not in budgets[2]


class TestTheMonthPager:
    """The header equation, paged into future months: bills at face value,
    the verdict chip strip naming the month that breaks."""

    ENTRY = {
        "period_month": 202610,
        "income_due": 1_405_028,
        "bills_due": 1_286_346,
        "budgets": 370_486,
        "goals": 27_273,
        "envelopes": 4_333,
        "month_net": -283_410,
        "start_balance": 120_000,
        "end_balance": -163_410,
    }

    def test_month_label(self) -> None:
        assert outlook_month_label(202610) == "October 2026"
        assert outlook_month_label(202701) == "January 2027"

    def test_future_month_cells_mirror_the_header_shape(self) -> None:
        cells = outlook_stats_cells(self.ENTRY)
        assert [c[0] for c in cells] == ["Income", "Bills", "Budgets", "October 2026"]
        income, bills, budgets, verdict = cells
        assert income[1] == "$14,050.28"
        assert "due" in income[2]
        assert bills[1] == "$12,863.46"
        assert budgets[1] == "$3,704.86"
        assert "+ $272.73 to goals" in budgets[2]
        assert verdict[1] == "-$2,834.10"
        assert verdict[3] == Theme.Colors.ERROR

    def test_a_good_future_month_wears_the_accent(self) -> None:
        cells = outlook_stats_cells({**self.ENTRY, "month_net": 166_590})
        verdict = cells[3]
        assert verdict[1] == "+$1,665.90"
        assert verdict[3] == Theme.Colors.ACCENT

    def test_chips_carry_the_ending_balance_not_the_rate(self) -> None:
        """The chip answers "can I pay that month" - the projected cash
        it ENDS with, compounded from today's real balance. Red means
        literally out of money, not merely a negative month."""
        label, color = outlook_chip(self.ENTRY)
        assert label == "Oct -$1,634"
        assert color == Theme.Colors.ERROR
        label, color = outlook_chip({**self.ENTRY, "end_balance": 124_000})
        assert label == "Oct $1,240"
        assert color == Theme.Colors.TEXT_SECONDARY

    def test_the_verdict_caption_names_the_landing(self) -> None:
        cells = outlook_stats_cells(self.ENTRY)
        verdict = cells[3]
        assert "ends around -$1,634.10" in verdict[2]


class TestEverythingElseCell:
    """The sixth term gets its own cell - it was bigger than the budgets
    figure when discovered, and a caption cannot carry the load-bearing
    number of the page. Hidden entirely at zero (fresh installs keep the
    four-cell strip)."""

    def test_the_cell_appears_with_the_observed_rate(self) -> None:
        cells = budget_stats_cells({**STATS, "everything_else": 794_400})
        labels = [c[0] for c in cells]
        assert labels == ["Income", "Bills", "Budgets", "Everything else", "This month"]
        cell = next(c for c in cells if c[0] == "Everything else")
        assert cell[1] == "$7,944.00"
        assert "observed" in cell[2]

    def test_the_outlook_strip_gains_it_too(self) -> None:
        entry = {**TestTheMonthPager.ENTRY, "everything_else": 794_400}
        cells = outlook_stats_cells(entry)
        labels = [c[0] for c in cells]
        assert "Everything else" in labels
        assert labels[-1] == "October 2026"


class TestHeaderStaysShort:
    """The Budget header spends its height on numbers, not prose: the
    explainer sentence rides an info-icon tooltip (not its own line) and
    the month pager shares the title's row instead of claiming one."""

    def test_the_explainer_is_a_tooltip_not_a_line(self) -> None:
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.BudgetPanel.__init__)
        start = source.index("Your plan checked against")
        assert "tooltip=(" in source[max(0, start - 200) : start]

    def test_the_pager_rides_the_title_row(self) -> None:
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        assert "_pager_slot" in inspect.getsource(finance_modal.BudgetPanel.__init__)
        strip = inspect.getsource(finance_modal.BudgetPanel._stats_strip)
        assert "_month_pager" not in strip


class TestStatPopups:
    """Click a header cell, get its rows: one shared popup, five feeds.

    The equation feed is built client-side from the SAME stats dict the
    cells render from, so the popup can never disagree with the strip."""

    def test_equation_rows_state_the_whole_arithmetic(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import (
            equation_rows,
        )

        stats = {
            "income_total": 1_000_000,
            "fixed_total": 563_896,
            "flexible_allocated": 289_439,
            "goals_total": 10_000,
            "envelopes_total": 4_333,
            "everything_else": 375_156,
            "month_net": -242_824,
        }
        rows = equation_rows(stats)
        assert [(r["label"], r["value"]) for r in rows] == [
            ("Income", 1_000_000),
            ("Bills", -563_896),
            ("Budgets", -289_439),
            ("Goals", -10_000),
            ("Envelopes", -4_333),
            ("Everything else", -375_156),
            ("This month", -242_824),
        ]

    def test_zero_terms_stay_out_of_the_equation(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import (
            equation_rows,
        )

        stats = {
            "income_total": 1_000_000,
            "fixed_total": 563_896,
            "flexible_allocated": 289_439,
            "goals_total": 0,
            "envelopes_total": 0,
            "everything_else": 0,
            "month_net": 146_665,
        }
        labels = [r["label"] for r in equation_rows(stats)]
        assert "Goals" not in labels
        assert "Envelopes" not in labels
        assert "Everything else" not in labels
        assert labels[-1] == "This month"

    def test_the_panel_renders_rows_and_footer(self) -> None:
        from app.components.frontend.dashboard.modals.finance_modal import (
            stat_detail_panel,
        )

        panel = stat_detail_panel(
            "Everything else",
            [
                {"label": "Dentist", "value": 73_209, "caption": "3 rows"},
                {"label": "Cash & ATM", "value": 22_000, "caption": "6 rows"},
            ],
            footer="May - Jul 2026 average",
        )

        def texts(node):
            found = []
            value = getattr(node, "value", None)
            if isinstance(value, str) and value:
                found.append(value)
            for child in getattr(node, "controls", None) or []:
                found.extend(texts(child))
            content = getattr(node, "content", None)
            if content is not None:
                found.extend(texts(content))
            return found

        rendered = " ".join(texts(panel))
        assert "Dentist" in rendered
        assert "$732.09" in rendered
        assert "3 rows" in rendered
        assert "May - Jul 2026 average" in rendered

    def test_the_cells_are_wired_to_open_it(self) -> None:
        import inspect

        from app.components.frontend.dashboard.modals import finance_modal

        source = inspect.getsource(finance_modal.BudgetPanel)
        assert "_stat_detail" in source
        assert "_open_stat_detail" in source
        assert "stat-details" in source
        # The verdict popup builds from the SAME stats the strip renders.
        assert "equation_rows(" in source
