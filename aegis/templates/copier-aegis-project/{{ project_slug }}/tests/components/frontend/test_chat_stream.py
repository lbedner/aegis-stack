"""Pure logic of the chat panel's streaming layer."""

import json

from app.components.frontend.controls.chat.stream import (
    StreamAccumulator,
    balance_fences,
    footer_line,
    narration_note,
    tool_label,
    trace_failed,
    trace_label,
    trace_output,
)


class TestBalanceFences:
    def test_closes_an_open_code_fence(self) -> None:
        partial = "Here is code:\n```python\nx = 1"
        assert balance_fences(partial).endswith("\n```")

    def test_leaves_balanced_text_alone(self) -> None:
        text = "Done:\n```python\nx = 1\n```\nAll set."
        assert balance_fences(text) == text

    def test_plain_text_untouched(self) -> None:
        assert balance_fences("no code here") == "no code here"


class TestStreamAccumulator:
    def test_chunks_accumulate_in_order(self) -> None:
        acc = StreamAccumulator()
        acc.add_chunk({"content": "Hello ", "conversation_id": "c1"})
        acc.add_chunk({"content": "world"})

        assert acc.text == "Hello world"
        assert acc.conversation_id == "c1"

    def test_snapshot_is_fence_balanced_with_cursor(self) -> None:
        acc = StreamAccumulator()
        acc.add_chunk({"content": "```python\nx = 1"})

        snapshot = acc.snapshot()

        assert snapshot.count("```") % 2 == 0
        assert "▌" in snapshot

    def test_final_event_carries_footer_metadata(self) -> None:
        acc = StreamAccumulator()
        acc.add_chunk({"content": "answer"})
        acc.add_final(
            {
                "content": "answer",
                "conversation_id": "c2",
                "model": "qwen3.8:27b-mlx",
                "cost": 0.0,
                "gen_tps": 28.5,
            }
        )

        assert acc.final_text() == "answer"
        assert acc.conversation_id == "c2"
        assert acc.final_meta["model"] == "qwen3.8:27b-mlx"
        assert acc.final_meta["gen_tps"] == 28.5
        # Metadata is kept raw; footer_line decides that $0.0000 is noise.
        assert acc.final_meta["cost"] == 0.0
        assert "$" not in footer_line(acc.final_meta)

    def test_non_delta_final_fills_empty_stream(self) -> None:
        acc = StreamAccumulator()
        acc.add_final({"content": "whole answer", "conversation_id": "c3"})

        assert acc.final_text() == "whole answer"


class TestToolEvents:
    def test_reset_drops_pre_tool_narration(self) -> None:
        """Commentary streamed before a tool call is not the answer."""
        acc = StreamAccumulator()
        acc.add_chunk({"content": "Let me check. ", "conversation_id": "c1"})
        acc.reset_text()
        acc.add_chunk({"content": "The answer is 4."})

        assert acc.text == "The answer is 4."
        assert acc.conversation_id == "c1"  # ids survive the reset

    def test_tool_label_names_the_call_with_compact_args(self) -> None:
        assert tool_label("ledger", '{"months": 3, "detail": "monthly"}') == (
            "ledger(months=3, detail=monthly)"
        )
        assert tool_label("accounts") == "accounts()"
        assert tool_label("quote", "not-json") == "quote(not-json)"
        assert tool_label("") == "working..."

    def test_tool_label_shows_a_script_by_its_first_line(self) -> None:
        """run_code trail lines say what the script was FOR."""
        assert tool_label("run_code", '{"code": "subs = [t for t in txs]"}') == (
            "run_code: subs = [t for t in txs]"
        )

    def test_trace_label_previews_scripts_and_args(self) -> None:
        assert trace_label(
            {"tool": "run_code", "code": "# setup\ntx = await ledger()\nx"}
        ) == "run_code: tx = await ledger()"
        assert trace_label({"tool": "ledger", "args": '{"months": 3}'}) == (
            "ledger(months=3)"
        )

    def test_trace_output_unwraps_run_code_results(self) -> None:
        wrapped = '{"return_value": {"output": "23 visits\\n$263.38"}}'
        assert trace_output({"result": wrapped}) == "23 visits\n$263.38"
        assert trace_output({"result": "plain text"}) == "plain text"
        assert trace_output({}) == ""

    def test_trace_output_pretty_prints_printed_literals(self) -> None:
        """A long printed list of dicts wraps into an indented pprint
        block - the expanded run reads like data, not a log dump."""
        printed = (
            "4876\n"
            "[{'date': '2026-08-20', 'payee': \"McDonald's\","
            " 'amount_cents': -615,"
            " 'category': 'Food & Dining:Eating Out / Delivery',"
            " 'account': 'TOTAL CHECKING (CHASE)', 'pending': False}]"
        )
        wrapped = json.dumps({"return_value": {"output": printed}})

        shown = trace_output({"result": wrapped})

        first, rest = shown.split("\n", 1)
        assert first == "4876"
        assert rest.startswith("[{'date': '2026-08-20',")
        assert "'pending': False}]" in rest
        assert len(rest.splitlines()) > 1

    def test_trace_output_unwraps_the_flat_output_envelope(self) -> None:
        """Some results arrive as {"output": ...} with no return_value
        wrapper; the printed text still shows, not the JSON envelope."""
        wrapped = json.dumps({"output": "dict_keys(['total', 'returned'])"})

        assert trace_output({"result": wrapped}) == (
            "dict_keys(['total', 'returned'])"
        )

    def test_trace_failed_flags_sandbox_failure_reports(self) -> None:
        assert trace_failed({"result": "Type error in code:\nerror[x]"})
        assert trace_failed({"result": "...\nFix the errors and try again."})
        assert not trace_failed({"result": '{"return_value": 4}'})
        assert not trace_failed({})

    def test_accumulator_keeps_the_final_tool_trace(self) -> None:
        acc = StreamAccumulator()
        acc.add_final(
            {"content": "done", "tool_trace": [{"tool": "run_code", "code": "x"}]}
        )
        assert acc.tool_trace == [{"tool": "run_code", "code": "x"}]

    def test_narration_note_clips_and_flattens(self) -> None:
        assert narration_note("Let me\ncheck the data. ") == "Let me check the data."
        assert narration_note("   ") == ""
        long = "x" * 150
        assert len(narration_note(long)) == 100
        assert narration_note(long).endswith("...")


class TestFooterLine:
    def test_composes_model_tps_and_cost(self) -> None:
        line = footer_line({"model": "gpt-4", "gen_tps": 12.0, "cost": 0.0123})
        assert "gpt-4" in line
        assert "12.0 tps" in line
        assert "$0.0123" in line

    def test_empty_meta_renders_nothing(self) -> None:
        assert footer_line({}) == ""
