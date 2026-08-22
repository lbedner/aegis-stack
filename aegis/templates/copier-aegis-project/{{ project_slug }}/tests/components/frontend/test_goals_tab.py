"""The Goals sub-tab's pure pieces (GL-07..09, tracker #939).

Card copy (amounts line, ETA caption), the Close-the-gap row copy for
both row kinds, the linkable-account options, and the dollars parser -
everything the tab renders that can be tested without a page.
"""

from app.components.frontend.theme import AegisTheme as Theme
from app.components.frontend.dashboard.modals.finance_modal import (
    close_gap_row_copy,
    contribution_preview,
    dollars_to_cents,
    envelope_card,
    goal_amounts_line,
    goal_eta_caption,
    linkable_account_options,
    savings_goal_card,
    goal_shortfall_caption,
    target_note_copy,
)

GOAL = {
    "account_id": 71,
    "name": "Vacation",
    "funding": "virtual",
    "status": "active",
    "target_amount": 300_000,
    "target_date": "2027-06-01",
    "monthly_contribution": 25_000,
    "balance": 120_000,
    "progress": 0.4,
    "monthly_need": 25_000,
    "eta": "2027-06-01",
}


def _texts(control) -> list[str]:
    if control is None:
        return []
    found = []
    value = getattr(control, "value", None)
    if isinstance(value, str) and value:
        found.append(value)
    for child in getattr(control, "controls", None) or []:
        found.extend(_texts(child))
    found.extend(_texts(getattr(control, "content", None)))
    return found


class TestCardCopy:
    def test_amounts_line(self) -> None:
        assert goal_amounts_line(GOAL) == "$1,200.00 of $3,000.00"

    def test_eta_caption_lands(self) -> None:
        assert goal_eta_caption(GOAL) == "$250.00/mo · lands Jun 1, 2027"

    def test_eta_caption_never(self) -> None:
        goal = {**GOAL, "eta": None, "monthly_need": 0}
        assert goal_eta_caption(goal) == "$0.00/mo · at this rate: never"

    def test_paused_and_reached_say_so(self) -> None:
        assert goal_eta_caption({**GOAL, "status": "paused"}) == "Paused"
        assert goal_eta_caption({**GOAL, "status": "reached"}) == "Reached"
        # A full balance reads as reached even before the status flips.
        assert goal_eta_caption({**GOAL, "progress": 1.0}) == "Reached"


class TestCard:
    def _noop(self) -> None:
        return None

    def _card(self, goal):
        return savings_goal_card(
            goal,
            on_contribute=self._noop,
            on_toggle_pause=self._noop,
            on_edit=self._noop,
            on_remove=self._noop,
        )

    def test_the_card_carries_the_facts(self) -> None:
        rendered = " ".join(_texts(self._card(GOAL)))
        assert "Vacation" in rendered
        assert "$1,200.00 of $3,000.00" in rendered
        assert "lands Jun 1, 2027" in rendered
        # Budget-line geometry: the percent sits top-right, like a limit.
        assert "40%" in rendered

    def test_a_linked_goal_is_labelled(self) -> None:
        rendered = " ".join(_texts(self._card({**GOAL, "funding": "linked"})))
        assert "linked" in rendered.lower()

    def test_pause_resume_follows_status(self) -> None:
        active = " ".join(_texts(self._card(GOAL)))
        paused = " ".join(_texts(self._card({**GOAL, "status": "paused"})))
        assert "Pause" in active
        assert "Resume" in paused


class TestCloseGapRows:
    def test_a_pause_row_speaks_recovery(self) -> None:
        title, delta, sub = close_gap_row_copy(
            {"kind": "pause_goal", "label": "Vacation", "recovered": 25_000}
        )
        assert title == "Pause Vacation"
        assert delta == "+$250.00"
        assert "resume" in sub.lower()

    def test_a_cut_row_is_unchanged_in_spirit(self) -> None:
        title, delta, sub = close_gap_row_copy(
            {
                "kind": "cut_budget",
                "label": "Dining out",
                "cut": 4_500,
                "allocated_amount": 30_000,
                "suggested_amount": 25_500,
            }
        )
        assert title == "Dining out"
        assert delta == "-$45.00"
        assert "$300.00 -> $255.00" == sub


class TestLinkableAccounts:
    ACCOUNTS = [
        {"id": 1, "name": "Checking", "account_type": "checking", "classification": "asset"},
        {"id": 2, "name": "Savings", "account_type": "savings", "classification": "asset"},
        {"id": 3, "name": "AMEX", "account_type": "credit_card", "classification": "liability"},
        {"id": 4, "name": "Old goal", "account_type": "goal", "classification": "asset"},
    ]

    def test_only_real_asset_accounts_are_linkable(self) -> None:
        options = linkable_account_options(self.ACCOUNTS)
        labels = [label for _key, label in options]
        assert "Savings" in labels and "Checking" in labels
        assert "AMEX" not in labels  # a debt is not a dream
        assert "Old goal" not in labels  # goals don't nest


class TestDollarsToCents:
    def test_parses_money_shapes(self) -> None:
        assert dollars_to_cents("3,000") == 300_000
        assert dollars_to_cents("$1,200.50") == 120_050
        assert dollars_to_cents(" 12 ") == 1_200

    def test_junk_is_none(self) -> None:
        assert dollars_to_cents("") is None
        assert dollars_to_cents("a lot") is None
        assert dollars_to_cents(None) is None


class TestRuleCopy:
    """GL-15: cards name their rule, and the dialog's live preview names
    the base - the support question is always '10% of WHAT'."""

    def test_percent_goal_caption_names_the_rule(self) -> None:
        goal = {
            **GOAL,
            "contribution_kind": "percent_income",
            "contribution_pct_bps": 1_000,
            "monthly_need": 82_000,
            "eta": "2027-06-01",
        }
        caption = goal_eta_caption(goal)
        assert caption == "$820.00/mo (10% of income) · lands Jun 1, 2027"

    def test_surplus_goal_caption_names_the_sweep(self) -> None:
        goal = {
            **GOAL,
            "contribution_kind": "surplus",
            "monthly_need": 40_000,
            "eta": None,
        }
        assert goal_eta_caption(goal) == "$400.00/mo (surplus) · at this rate: never"

    def test_fixed_goal_caption_is_unchanged(self) -> None:
        assert goal_eta_caption(GOAL) == "$250.00/mo · lands Jun 1, 2027"

    def test_percent_preview_names_the_base(self) -> None:
        assert (
            contribution_preview("percent_income", "10", income_total=820_000)
            == "10% of $8,200.00/mo = $820.00/mo"
        )

    def test_percent_preview_with_no_income_warns(self) -> None:
        line = contribution_preview("percent_income", "10", income_total=0)
        assert "no confirmed income" in line

    def test_surplus_preview_says_what_it_does(self) -> None:
        line = contribution_preview("surplus", "", income_total=820_000)
        assert "left" in line.lower()

    def test_fixed_preview_is_empty(self) -> None:
        assert contribution_preview("fixed", "250", income_total=820_000) == ""


class TestEnvelopeCards:
    """The Envelopes sub-tab: balance is the headline, negative reads in
    error red, the standing credit captions itself."""

    ENVELOPE = {
        "account_id": 91,
        "name": "Allowance",
        "balance": 2_750,
        "monthly_credit": 4_000,
        "auto_credit": True,
    }

    def _noop(self) -> None:
        return None

    def _card(self, env):
        return envelope_card(
            env,
            on_spend=self._noop,
            on_credit=self._noop,
            on_edit=self._noop,
            on_remove=self._noop,
        )

    def test_the_card_carries_the_facts(self) -> None:
        rendered = " ".join(_texts(self._card(self.ENVELOPE)))
        assert "Allowance" in rendered
        assert "$27.50" in rendered
        assert "+$40.00/mo" in rendered

    def test_manual_credit_has_no_monthly_caption(self) -> None:
        rendered = " ".join(
            _texts(self._card({**self.ENVELOPE, "auto_credit": False}))
        )
        assert "+$40.00/mo" not in rendered

    def test_a_negative_balance_reads_red(self) -> None:
        card = self._card({**self.ENVELOPE, "balance": -1_250})
        texts = [
            t
            for t in _walk_controls(card)
            if getattr(t, "value", None) == "-$12.50"
        ]
        assert texts and texts[0].color == Theme.Colors.ERROR


def _walk_controls(control):
    if control is None:
        return
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk_controls(child)
    content = getattr(control, "content", None)
    if content is not None:
        yield from _walk_controls(content)


class TestTargetNoteCopy:
    """GL-16: the goal dialog's line under a relative target. The number
    comes from the server; this only decides how to say it."""

    def test_a_fixed_target_says_nothing(self) -> None:
        assert target_note_copy("fixed", "", 300_000) == ""

    def test_it_renders_the_servers_answer(self) -> None:
        assert (
            target_note_copy("months_of_expenses", "3", 900_000)
            == "3 months of expenses = $9,000.00"
        )

    def test_nothing_to_size_against_says_why_instead_of_zero(self) -> None:
        line = target_note_copy("months_of_expenses", "3", 0)
        assert "Nothing to size against" in line
        assert "$0.00" not in line

    def test_junk_months_ask_for_a_number(self) -> None:
        for raw in ("", "soon", "0", "-3"):
            assert target_note_copy("months_of_expenses", raw, 900_000) == (
                "Enter a number of months, e.g. 3"
            )


class TestGoalShortfallCaption:
    """#961: what the Goals tab says when the plan outruns the month."""

    def test_a_plan_that_fits_says_nothing(self) -> None:
        assert goal_shortfall_caption(0) == ""
        assert goal_shortfall_caption(-500) == ""

    def test_it_names_the_gap(self) -> None:
        assert goal_shortfall_caption(140_500) == (
            "Goals ask $1,405.00 more than this month has."
        )
