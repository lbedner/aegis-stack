"""The history budget scales with the model, not a constant.

A 6k-char window sized for small local models is how a long-context
agent "forgets" an allocation it computed minutes ago; an unbounded one
re-bills the whole conversation every turn. The budget is a fraction of
the ACTIVE model's context window, floored and capped.
"""

from app.services.ai.service.prompt import (
    HISTORY_CHAR_BUDGET_DEFAULT,
    HISTORY_CHAR_BUDGET_MAX,
    HISTORY_CHAR_BUDGET_MIN,
    _history_start,
    history_char_budget,
)


class TestHistoryCharBudget:
    def test_unknown_context_gets_the_default(self) -> None:
        assert history_char_budget(None) == HISTORY_CHAR_BUDGET_DEFAULT
        assert history_char_budget(0) == HISTORY_CHAR_BUDGET_DEFAULT

    def test_small_models_are_floored(self) -> None:
        """8k tokens * 4 chars * 5% = 1.6k chars - below the floor a
        conversation stops being a conversation."""
        assert history_char_budget(8_000) == HISTORY_CHAR_BUDGET_MIN

    def test_mid_context_scales_proportionally(self) -> None:
        # 128k tokens -> 128_000 * 4 * 0.05 = 25_600 chars
        assert history_char_budget(128_000) == 25_600

    def test_huge_context_is_capped_for_cost(self) -> None:
        """History is re-sent on every turn; a 1M-context model must not
        turn each message into a dollar of replayed transcript."""
        assert history_char_budget(1_050_000) == HISTORY_CHAR_BUDGET_MAX

    def test_the_bounds_are_ordered(self) -> None:
        assert (
            HISTORY_CHAR_BUDGET_MIN
            <= HISTORY_CHAR_BUDGET_DEFAULT
            <= HISTORY_CHAR_BUDGET_MAX
        )


class TestHistoryStart:
    """Past the budget, history is cut a slab at a time (``_history_start``):
    sixty messages of 1,030 chars, against a 20,000-char budget."""

    LENGTHS = [1_030] * 60
    BUDGET = 20_000
    TURNS = range(20, 61)  # every turn past the budget

    def test_most_turns_replay_the_start_the_last_one_did(self) -> None:
        starts = [_history_start(self.LENGTHS[:n], self.BUDGET) for n in self.TURNS]

        moved = sum(a != b for a, b in zip(starts, starts[1:]))

        assert moved <= 0.2 * (len(starts) - 1)

    def test_a_cut_keeps_half_the_budget_less_one_message(self) -> None:
        for n in self.TURNS:
            kept = sum(self.LENGTHS[_history_start(self.LENGTHS[:n], self.BUDGET) : n])

            assert self.BUDGET // 2 - self.LENGTHS[0] <= kept <= self.BUDGET

    def test_a_thread_inside_the_budget_keeps_everything(self) -> None:
        assert _history_start([100, 100], self.BUDGET) == 0
