"""The engine benchmark aims at the route you asked for, and reads the report.

Both failure modes here are quiet ones: a parser that stops matching
reports zeros, and a half-substituted path benchmarks a 404. Either reads
like a real result.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# Patch where the name is READ, not where it used to live: ``choose_driver``
# resolves ``AB`` and ``shutil`` in ``bench_drivers``, so patching ``bench``
# would set an attribute nothing looks at and the test would pass blind.
from app.cli import bench_drivers
from app.cli.bench_drivers import choose_driver, parse_ab, substitute_path_params

AB_REPORT = """Concurrency Level:      50
Time taken for tests:   0.361 seconds
Complete requests:      3000
Failed requests:        0
Total transferred:      744000 bytes
Requests per second:    8312.37 [#/sec] (mean)
Time per request:       6.015 [ms] (mean)
Transfer rate:          2013.15 [Kbytes/sec] received

Percentage of the requests served within a certain time (ms)
  50%      6
  66%      7
  95%      7
  99%      8
 100%     14 (longest request)
"""


def test_the_headline_numbers_come_back() -> None:
    sample = parse_ab(AB_REPORT)

    assert sample.throughput == pytest.approx(8312.37)
    assert sample.p50_ms == pytest.approx(6.0)
    assert sample.p95_ms == pytest.approx(7.0)
    assert sample.p99_ms == pytest.approx(8.0)
    assert sample.failed == 0


def test_failures_are_not_silently_zero() -> None:
    sample = parse_ab(
        AB_REPORT.replace("Failed requests:        0", "Failed requests:        17")
    )

    assert sample.failed == 17


def test_unparseable_output_raises_rather_than_reporting_zero() -> None:
    with pytest.raises(ValueError, match="no throughput line"):
        parse_ab("ab: command not understood\n")


class TestRouteTargeting:
    def test_placeholders_are_filled(self) -> None:
        filled = substitute_path_params(
            "/api/v1/jobs/{job_id}/events", {"job_id": "abc-123"}
        )

        assert filled == "/api/v1/jobs/abc-123/events"

    def test_every_placeholder_is_filled(self) -> None:
        filled = substitute_path_params(
            "/api/v1/items/{item_id}/owner/{user_id}",
            {"item_id": "42", "user_id": "u-9"},
        )

        assert filled == "/api/v1/items/42/owner/u-9"

    def test_a_missing_param_refuses_to_benchmark_a_404(self) -> None:
        # Left alone, this hits a URL with a literal brace in it and
        # reports fast uniform 404s that look like a fine result.
        with pytest.raises(ValueError, match="job_id"):
            substitute_path_params("/api/v1/jobs/{job_id}", {})


class TestDriverChoice:
    def test_ab_drives_what_it_can(self) -> None:
        assert choose_driver("auto", "GET")[0] == "ab"
        assert choose_driver("auto", "POST")[0] == "ab"

    def test_methods_ab_cannot_issue_fall_back_with_a_reason(self) -> None:
        driver, reason = choose_driver("auto", "DELETE")

        assert driver == "api-load-test"
        assert reason is not None and "DELETE" in reason

    def test_an_explicit_choice_is_honored(self) -> None:
        assert choose_driver("api-load-test", "GET") == ("api-load-test", None)
        assert choose_driver("ab-docker", "GET") == ("ab-docker", None)

    def test_no_local_ab_falls_to_the_container_not_the_slow_client(self) -> None:
        # Most Linux has no ab, which is CI and most containers. Docker is
        # already required for a generated project, so the fallback that
        # can still saturate beats the one that cannot.
        with (
            patch.object(bench_drivers, "AB", "/nonexistent/ab"),
            patch.object(bench_drivers.shutil, "which", lambda name: "/usr/bin/docker"),
        ):
            driver, reason = choose_driver("auto", "GET")

        assert driver == "ab-docker"
        assert reason is not None

    def test_no_ab_and_no_docker_is_the_last_resort(self) -> None:
        with (
            patch.object(bench_drivers, "AB", "/nonexistent/ab"),
            patch.object(bench_drivers.shutil, "which", lambda name: None),
        ):
            driver, _ = choose_driver("auto", "GET")

        assert driver == "api-load-test"
