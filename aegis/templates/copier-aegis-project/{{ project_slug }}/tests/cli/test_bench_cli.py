"""Tests for the `bench engines` CLI command.

The command boots real servers, so everything below the measurement
boundary is mocked: these cover the argument handling and the reporting,
which is where the quiet wrong answers live.
"""

from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from app.cli import bench
from app.cli.main import app

runner = CliRunner()


def _sample(throughput: float) -> bench.Sample:
    return bench.Sample(
        throughput=throughput, p50_ms=5.0, p95_ms=6.0, p99_ms=7.0, failed=0
    )


def _run(args: list[str], samples: dict[str, float], loop: str = "uvloop") -> Any:
    """Invoke the command with the servers and the load generator stubbed."""

    def fake_measure(port: int, target: Any, requests: int, clients: int) -> Any:
        # Keyed by port so each engine can be given a different number.
        return _sample(samples[fake_measure.engines[port]])  # type: ignore[attr-defined]

    fake_measure.engines = {}  # type: ignore[attr-defined]

    class _Serving:
        def __init__(self, engine: str, port: int, loop_name: str) -> None:
            fake_measure.engines[port] = engine  # type: ignore[attr-defined]

        def __enter__(self) -> None:
            return None

        def __exit__(self, *exc: object) -> None:
            return None

    with (
        patch.object(bench, "_serving", _Serving),
        patch.object(bench, "_measure_ab", fake_measure),
        patch.object(bench, "resolve_loop", lambda choice=None: loop),
        patch.object(bench, "choose_driver", lambda requested, method: ("ab", None)),
    ):
        return runner.invoke(app, ["bench", "engines", *args])


class TestEnginesCommand:
    def test_it_reports_both_engines_and_the_loop(self) -> None:
        result = _run([], {"uvicorn": 5000.0, "granian": 8000.0})

        assert result.exit_code == 0, result.output
        assert "uvicorn" in result.output
        assert "granian" in result.output
        # The loop is the variable that silently changes the answer.
        assert "uvloop" in result.output

    def test_it_states_the_ratio(self) -> None:
        result = _run([], {"uvicorn": 4000.0, "granian": 8000.0})

        assert "2.00x" in result.output

    def test_a_loop_one_engine_cannot_run_skips_that_engine(self) -> None:
        result = _run([], {"granian": 8000.0}, loop="rloop")

        assert result.exit_code == 0, result.output
        assert "Skipping uvicorn" in result.output
        # One engine ran, so there is no comparison to state.
        assert "x uvicorn" not in result.output

    def test_an_unfilled_path_param_is_refused(self) -> None:
        result = _run(["--path", "/api/v1/jobs/{job_id}"], {})

        assert result.exit_code != 0
        assert "job_id" in result.output
