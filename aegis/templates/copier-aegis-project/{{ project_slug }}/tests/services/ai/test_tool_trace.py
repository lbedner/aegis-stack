"""Trace assembly: the run trail's entries survive their own size caps.

The result field is clipped for display, so anything the UI must PARSE
(the pending-change card payload) rides a separate compact marker that
no cap can corrupt - a 9-row batch once rendered no card because its
JSON was truncated mid-string.
"""

import json
from types import SimpleNamespace
from typing import Any


def _result_event(tool_name: str, content: Any) -> Any:
    return SimpleNamespace(
        part=SimpleNamespace(tool_name=tool_name, content=content, metadata=None)
    )


class TestProposalComponentMarker:
    def test_an_oversized_batch_result_still_carries_its_marker(self) -> None:
        from app.services.ai.service.trace import record_tool_result

        items = [
            {
                "id": n,
                "pending_change_id": n,
                "status": "pending",
                "display": [{"label": "Transaction", "value": "X" * 300}],
            }
            for n in range(9)
        ]
        result = {
            "batch_id": "b-123",
            "change_type": "transaction.tag",
            "title": "Tag a transaction",
            "count": 9,
            "items": items,
        }
        trace: list[dict[str, Any]] = [{"tool": "propose_many", "args": ""}]

        record_tool_result(trace, _result_event("propose_many", json.dumps(result)))

        entry = trace[0]
        assert len(entry["result"]) <= 2_000  # the display clip stands
        marker = entry["component"]
        assert marker["kind"] == "pending_change_batch"
        assert marker["batch_id"] == "b-123"
        assert marker["title"] == "Tag a transaction"

    def test_a_single_proposal_gets_its_marker_too(self) -> None:
        from app.services.ai.service.trace import record_tool_result

        result = {
            "pending_change_id": 7,
            "change_type": "transaction.categorize",
            "title": "Categorize a transaction",
            "status": "pending",
            "display": [],
        }
        trace: list[dict[str, Any]] = [{"tool": "propose", "args": ""}]

        record_tool_result(trace, _result_event("propose", json.dumps(result)))

        marker = trace[0]["component"]
        assert marker["kind"] == "pending_change"
        assert marker["pending_change_id"] == 7

    def test_a_failed_proposal_carries_no_marker(self) -> None:
        from app.services.ai.service.trace import record_tool_result

        result = {"error": "unknown change type", "registered_change_types": []}
        trace: list[dict[str, Any]] = [{"tool": "propose", "args": ""}]

        record_tool_result(trace, _result_event("propose", json.dumps(result)))

        assert "component" not in trace[0]

    def test_other_tools_are_untouched(self) -> None:
        from app.services.ai.service.trace import record_tool_result

        trace: list[dict[str, Any]] = [{"tool": "run_code", "code": "x"}]

        record_tool_result(trace, _result_event("run_code", '{"output": "6"}'))

        assert "component" not in trace[0]
