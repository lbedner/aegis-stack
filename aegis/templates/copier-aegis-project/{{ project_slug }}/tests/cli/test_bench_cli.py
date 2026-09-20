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


def _run_matrix(args: list[str], samples: dict[tuple[str, str], float]) -> Any:
    """Invoke with the loop axis swept rather than pinned.

    ``resolve_loop`` resolves each choice to itself here, so the test
    controls the matrix instead of the host's installed loops - except
    ``auto``, which the real one never returns, so the stub must not
    either or every engine would skip an un-runnable name.
    """
    # A list, not a dict by port: nothing binds here, so every run gets
    # the same free port back and a dict would keep only the last pair.
    ran: list[tuple[str, str]] = []
    current: dict[int, tuple[str, str]] = {}

    def fake_measure(port: int, target: Any, requests: int, clients: int) -> Any:
        return _sample(samples[current[port]])

    class _Serving:
        def __init__(self, engine: str, port: int, loop_name: str) -> None:
            ran.append((engine, loop_name))
            current[port] = (engine, loop_name)

        def __enter__(self) -> None:
            return None

        def __exit__(self, *exc: object) -> None:
            return None

    with (
        patch.object(bench, "_serving", _Serving),
        patch.object(bench, "_measure_ab", fake_measure),
        patch.object(
            bench,
            "resolve_loop",
            lambda choice=None: "uvloop" if choice == "auto" else choice,
        ),
        patch.object(bench, "choose_driver", lambda requested, method: ("ab", None)),
    ):
        result = runner.invoke(app, ["bench", "engines", *args])
    result.ran = sorted(ran)  # type: ignore[attr-defined]
    return result


class TestLoopMatrix:
    """``--loop`` repeats, and the sweep becomes engine x loop."""

    def test_two_loops_sweep_every_compatible_pair(self) -> None:
        result = _run_matrix(
            ["--loop", "uvloop", "--loop", "asyncio"],
            {
                ("uvicorn", "uvloop"): 5000.0,
                ("granian", "uvloop"): 8000.0,
                ("uvicorn", "asyncio"): 3000.0,
                ("granian", "asyncio"): 4000.0,
            },
        )

        assert result.exit_code == 0, result.output
        assert result.ran == [  # type: ignore[attr-defined]
            ("granian", "asyncio"),
            ("granian", "uvloop"),
            ("uvicorn", "asyncio"),
            ("uvicorn", "uvloop"),
        ]

    def test_an_incompatible_pair_drops_out_without_ending_the_sweep(self) -> None:
        """rloop is granian's alone and zuvloop is uvicorn's alone, so
        sweeping both is two runs and two skips - not a failure."""
        result = _run_matrix(
            ["--loop", "rloop", "--loop", "zuvloop"],
            {("granian", "rloop"): 8000.0, ("uvicorn", "zuvloop"): 6000.0},
        )

        assert result.exit_code == 0, result.output
        assert result.ran == [  # type: ignore[attr-defined]
            ("granian", "rloop"),
            ("uvicorn", "zuvloop"),
        ]
        assert "Skipping uvicorn" in result.output
        assert "Skipping granian" in result.output

    def test_the_same_loop_twice_is_run_once(self) -> None:
        result = _run_matrix(
            ["--loop", "uvloop", "--loop", "uvloop"],
            {("uvicorn", "uvloop"): 5000.0, ("granian", "uvloop"): 8000.0},
        )

        assert len(result.ran) == 2  # type: ignore[attr-defined]

    def test_the_ratio_names_the_pair_not_just_the_engine(self) -> None:
        """With a matrix the best and worst can differ by loop, so a bare
        engine name would not say what actually won."""
        result = _run_matrix(
            ["--loop", "uvloop", "--loop", "asyncio"],
            {
                ("uvicorn", "uvloop"): 4000.0,
                ("granian", "uvloop"): 8000.0,
                ("uvicorn", "asyncio"): 4000.0,
                ("granian", "asyncio"): 4000.0,
            },
        )

        assert "granian/uvloop" in result.output
        assert "2.00x" in result.output

    def test_no_loop_given_still_runs_the_resolved_default(self) -> None:
        """The old single-axis behaviour is the one-element matrix."""
        result = _run_matrix(
            [], {("uvicorn", "uvloop"): 5000.0, ("granian", "uvloop"): 8000.0}
        )

        assert result.exit_code == 0, result.output
        assert len(result.ran) == 2  # type: ignore[attr-defined]


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
