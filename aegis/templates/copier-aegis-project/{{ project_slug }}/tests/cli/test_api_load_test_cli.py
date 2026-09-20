"""
Tests for HTTP load-test CLI commands.

The CLI is a thin wrapper around ``APILoadTestService`` and
``discovery.list_routes``. These tests mock both at the CLI-module
boundary so they don't need a running FastAPI app or Redis instance.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from app.cli.main import app
from app.services.load_test.api.models import (
    APILoadTestConfiguration,
    APILoadTestMetrics,
    APILoadTestResult,
    ErrorSample,
    RouteInfo,
)

runner = CliRunner()


def _make_result(test_id: str = "t1", failures: int = 0) -> APILoadTestResult:
    sent = 10
    completed = sent - failures
    return APILoadTestResult(
        status="completed",
        test_id=test_id,
        configuration=APILoadTestConfiguration(
            test_id=test_id,
            method="GET",
            path="/health",
            requests=sent,
            clients=2,
        ),
        metrics=APILoadTestMetrics(
            tasks_sent=sent,
            tasks_completed=completed,
            tasks_failed=failures,
            total_duration_seconds=1.0,
            overall_throughput=float(sent),
            failure_rate_percent=(failures / sent * 100),
            completion_percentage=(completed / sent * 100),
            latency_ms_p50=10.0,
            latency_ms_p95=25.0,
            latency_ms_p99=40.0,
            latency_ms_max=50.0,
            status_codes={200: completed, **({500: failures} if failures else {})},
            errors=(
                [ErrorSample(request_index=0, error_type="HTTP500", message="x")]
                if failures
                else []
            ),
        ),
        start_time="2026-05-17T14:00:00+00:00",
        end_time="2026-05-17T14:00:01+00:00",
    )


class TestHelpCommands:
    def test_group_help(self):
        result = runner.invoke(app, ["api-load-test", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "run" in result.output
        assert "results" in result.output
        assert "recent" in result.output

    def test_list_help(self):
        result = runner.invoke(app, ["api-load-test", "list", "--help"])
        assert result.exit_code == 0

    def test_run_help(self):
        """Assert on the option's help description rather than its flag
        name. Typer's rich help renders narrow columns when the option
        list is long, dropping the long flag (``--method``) in favour of
        the short alias (``-m``) so a literal ``--method in output``
        check is fragile."""
        result = runner.invoke(app, ["api-load-test", "run", "--help"])
        assert result.exit_code == 0
        assert "HTTP method" in result.output
        assert "Total requests" in result.output
        assert "Concurrent" in result.output


class TestListCommand:
    @patch("app.cli.api_load_test.list_routes")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_list_renders_routes(self, mock_get_app, mock_list_routes):
        mock_get_app.return_value = MagicMock()
        mock_list_routes.return_value = [
            RouteInfo(method="GET", path="/health", requires_auth=False, tags=["sys"]),
            RouteInfo(
                method="POST", path="/api/users", requires_auth=True, tags=["users"]
            ),
        ]
        result = runner.invoke(app, ["api-load-test", "list"])
        assert result.exit_code == 0
        assert "/health" in result.output
        assert "/api/users" in result.output
        assert "GET" in result.output
        assert "POST" in result.output

    @patch("app.cli.api_load_test.list_routes")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_list_shows_path_params_column_when_present(
        self, mock_get_app, mock_list_routes
    ):
        """PARAMS column should appear (and be populated) when any discovered
        route has placeholders. Static-only stacks shouldn't get a noisy
        empty column."""
        mock_get_app.return_value = MagicMock()
        mock_list_routes.return_value = [
            RouteInfo(method="GET", path="/health", requires_auth=False, tags=[]),
            RouteInfo(
                method="GET",
                path="/users/{user_id}",
                requires_auth=False,
                tags=["users"],
                path_params=["user_id"],
            ),
        ]
        result = runner.invoke(app, ["api-load-test", "list"])
        assert result.exit_code == 0
        assert "user_id" in result.output

    @patch("app.cli.api_load_test.list_routes")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_list_passes_auth_dependency_when_available(
        self, mock_get_app, mock_list_routes
    ):
        """When the project has an auth service, the CLI must hand its auth
        callable to ``list_routes`` — otherwise the AUTH column always says
        ``no`` and the table lies."""
        mock_get_app.return_value = MagicMock()
        mock_list_routes.return_value = []
        # Patch the import inside the CLI so it appears to be available.
        sentinel_dep = object()
        with patch(
            "app.cli.api_load_test._get_auth_dependency", return_value=sentinel_dep
        ):
            result = runner.invoke(app, ["api-load-test", "list"])
        assert result.exit_code == 0
        # Confirm list_routes saw the dependency we wired in.
        kwargs = mock_list_routes.call_args.kwargs
        assert kwargs.get("auth_dependency") is sentinel_dep

    @patch("app.cli.api_load_test.list_routes")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_list_empty(self, mock_get_app, mock_list_routes):
        mock_get_app.return_value = MagicMock()
        mock_list_routes.return_value = []
        result = runner.invoke(app, ["api-load-test", "list"])
        assert result.exit_code == 0

    @patch("app.cli.api_load_test.list_routes")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_list_json_output(self, mock_get_app, mock_list_routes):
        mock_get_app.return_value = MagicMock()
        mock_list_routes.return_value = [
            RouteInfo(method="GET", path="/health", requires_auth=False, tags=[]),
        ]
        result = runner.invoke(app, ["api-load-test", "list", "--json"])
        assert result.exit_code == 0
        import json

        # Output may have extra whitespace; locate the JSON document
        payload = json.loads(result.output.strip())
        assert isinstance(payload, list)
        assert payload[0]["path"] == "/health"
        assert payload[0]["method"] == "GET"


class TestPathParamFlag:
    """``--path-param KEY=VAL`` (repeatable) plumbed into the config."""

    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_path_param_single(self, mock_get_app, mock_service_cls):
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result())
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/users/{user_id}",
                "--path-param",
                "user_id=abc-123",
                "--requests",
                "5",
                "--clients",
                "1",
                "--in-process",
            ],
        )
        assert result.exit_code == 0
        config = mock_service.run.call_args.args[0]
        assert config.path_params == {"user_id": "abc-123"}

    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_path_param_multiple(self, mock_get_app, mock_service_cls):
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result())
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/items/{item_id}/owner/{user_id}",
                "--path-param",
                "item_id=42",
                "--path-param",
                "user_id=u-9",
                "--requests",
                "3",
                "--clients",
                "1",
                "--in-process",
            ],
        )
        assert result.exit_code == 0
        config = mock_service.run.call_args.args[0]
        assert config.path_params == {"item_id": "42", "user_id": "u-9"}

    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_run_without_required_path_param_exits_nonzero(self, mock_get_app):
        """Running a templated path without supplying ``--path-param`` must
        surface a friendly error (from the service's substitution check),
        not silently 404 against ``{user_id}``."""
        mock_get_app.return_value = MagicMock()
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/users/{user_id}",
                "--requests",
                "3",
                "--clients",
                "1",
                "--in-process",
            ],
        )
        assert result.exit_code != 0


class TestRunCommand:
    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_run_basic(self, mock_get_app, mock_service_cls):
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result())
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/health",
                "--requests",
                "10",
                "--clients",
                "2",
                "--in-process",
            ],
        )
        assert result.exit_code == 0
        assert "/health" in result.output
        assert mock_service.run.await_count == 1
        call_config = mock_service.run.call_args.args[0]
        assert call_config.path == "/health"
        assert call_config.requests == 10
        assert call_config.clients == 2
        assert call_config.in_process is True

    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_run_exit_zero_even_when_endpoint_errored(
        self, mock_get_app, mock_service_cls
    ):
        """A load test that completed its requests succeeded as a test,
        regardless of how the endpoint responded. Users gate CI on
        ``--json`` themselves; the CLI doesn't conflate endpoint health
        with test health."""
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result(failures=10))
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/health",
                "--requests",
                "10",
                "--clients",
                "2",
                "--in-process",
            ],
        )
        assert result.exit_code == 0

    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_run_report_does_not_pronounce_pass_or_fail(
        self, mock_get_app, mock_service_cls
    ):
        """The report shows stats, not a verdict. Whether the endpoint
        behaved correctly is for the operator to decide from the data."""
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result(failures=3))
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/health",
                "--requests",
                "10",
                "--clients",
                "2",
                "--in-process",
            ],
        )
        assert "PASSED" not in result.output
        assert "FAILED" not in result.output

    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_run_with_post_payload(self, mock_get_app, mock_service_cls):
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result())
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/echo",
                "--method",
                "POST",
                "--payload",
                '{"value": 42}',
                "--requests",
                "10",
                "--clients",
                "2",
                "--in-process",
            ],
        )
        assert result.exit_code == 0
        call_config = mock_service.run.call_args.args[0]
        assert call_config.method == "POST"
        assert call_config.payload == {"value": 42}

    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_run_with_headers(self, mock_get_app, mock_service_cls):
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result())
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/health",
                "--header",
                "X-Custom=hello",
                "--header",
                "X-Other=world",
                "--requests",
                "5",
                "--clients",
                "1",
                "--in-process",
                "--anon",
            ],
        )
        assert result.exit_code == 0
        call_config = mock_service.run.call_args.args[0]
        assert call_config.headers == {"X-Custom": "hello", "X-Other": "world"}

    # Patched where it is CALLED, not where the CLI re-exports it:
    # ``apply_auto_auth`` reads this name from its own module, so a patch
    # on ``app.cli.api_load_test`` would rebind a name nothing reads.
    # (``_get_auth_dependency`` above is the opposite case - the ``list``
    # command reads it from ``api_load_test``'s globals.)
    @patch(
        "app.cli.api_load_test_auth._ensure_active_verified_user",
        new_callable=AsyncMock,
    )
    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_run_auto_authenticates_by_default(
        self, mock_get_app, mock_service_cls, _mock_ensure_user
    ):
        """With no auth flag, requests are auto-authenticated when the auth
        service is installed, so gated routes work without manual login."""
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result())
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            ["api-load-test", "run", "/health", "-n", "2", "-c", "1", "--in-process"],
        )
        assert result.exit_code == 0
        call_config = mock_service.run.call_args.args[0]
        try:
            from app.core.security import create_access_token  # noqa: F401

            auth_installed = True
        except ImportError:
            auth_installed = False
        if auth_installed:
            assert call_config.headers.get("Authorization", "").startswith("Bearer ")
            assert call_config.auth_as in {"admin", "user"}
        else:
            assert "Authorization" not in call_config.headers
            assert call_config.auth_as is None

    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_run_anon_disables_auth(self, mock_get_app, mock_service_cls):
        """``--anon`` sends unauthenticated requests regardless of stack."""
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result())
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/health",
                "-n",
                "2",
                "-c",
                "1",
                "--in-process",
                "--anon",
            ],
        )
        assert result.exit_code == 0
        call_config = mock_service.run.call_args.args[0]
        assert "Authorization" not in call_config.headers
        assert call_config.auth_as is None

    @patch("app.cli.api_load_test.APILoadTestService")
    @patch("app.cli.api_load_test._get_fastapi_app")
    def test_run_json_output(self, mock_get_app, mock_service_cls):
        mock_get_app.return_value = MagicMock()
        mock_service = MagicMock()
        mock_service.run = AsyncMock(return_value=_make_result())
        mock_service_cls.return_value = mock_service
        result = runner.invoke(
            app,
            [
                "api-load-test",
                "run",
                "/health",
                "--requests",
                "10",
                "--clients",
                "2",
                "--in-process",
                "--json",
            ],
        )
        assert result.exit_code == 0
        import json

        # Locate JSON in output (Rich may emit progress before it)
        # Try the last "{" .. matching close
        # Simplest: the test result is the only top-level JSON object
        # Heuristic: split by newlines, find a line starting with "{"
        payload = json.loads(result.output)
        assert payload["test_id"] == "t1"
        assert payload["metrics"]["tasks_sent"] == 10


class TestResultsCommand:
    @patch("app.cli.api_load_test.APILoadTestService")
    def test_results_renders_existing(self, mock_service_cls):
        mock_service = MagicMock()
        mock_service.get_result = AsyncMock(return_value=_make_result("found"))
        mock_service_cls.return_value = mock_service
        result = runner.invoke(app, ["api-load-test", "results", "found"])
        assert result.exit_code == 0
        assert "found" in result.output

    @patch("app.cli.api_load_test.APILoadTestService")
    def test_results_nonzero_when_missing(self, mock_service_cls):
        mock_service = MagicMock()
        mock_service.get_result = AsyncMock(return_value=None)
        mock_service_cls.return_value = mock_service
        result = runner.invoke(app, ["api-load-test", "results", "missing"])
        assert result.exit_code != 0


class TestRecentCommand:
    @patch("app.cli.api_load_test.APILoadTestService")
    def test_recent_lists_runs(self, mock_service_cls):
        mock_service = MagicMock()
        mock_service.list_recent = AsyncMock(
            return_value=[_make_result("r1"), _make_result("r2")]
        )
        mock_service_cls.return_value = mock_service
        result = runner.invoke(app, ["api-load-test", "recent"])
        assert result.exit_code == 0
        assert "r1" in result.output
        assert "r2" in result.output

    @patch("app.cli.api_load_test.APILoadTestService")
    def test_recent_respects_limit(self, mock_service_cls):
        mock_service = MagicMock()
        mock_service.list_recent = AsyncMock(return_value=[])
        mock_service_cls.return_value = mock_service
        result = runner.invoke(app, ["api-load-test", "recent", "--limit", "3"])
        assert result.exit_code == 0
        mock_service.list_recent.assert_awaited_once_with(3)

    @patch("app.cli.api_load_test.APILoadTestService")
    def test_recent_empty(self, mock_service_cls):
        mock_service = MagicMock()
        mock_service.list_recent = AsyncMock(return_value=[])
        mock_service_cls.return_value = mock_service
        result = runner.invoke(app, ["api-load-test", "recent"])
        assert result.exit_code == 0
