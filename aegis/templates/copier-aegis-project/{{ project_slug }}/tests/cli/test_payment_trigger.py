"""
Tests for the ``my-app payment trigger`` wrapper.

The wrapper's job is pytest-style setup/teardown around ``stripe trigger``:
it shells out to stripe-cli, lets the event fire, then sweeps any
fixture Products/Prices the trigger left active in the Stripe test
account. We mock both the subprocess call and the stripe SDK so these
tests run offline.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.cli.payment import _CLI_FIXTURE_DESCRIPTION, _archive_fixtures
from tests._cli import invoke
from tests._secret_settings import secret_settings


def _fake_product(
    product_id: str, description: str = _CLI_FIXTURE_DESCRIPTION
) -> SimpleNamespace:
    return SimpleNamespace(id=product_id, description=description)


def _fake_price(price_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=price_id)


def _paging(items: list[SimpleNamespace]) -> MagicMock:
    """Build a mock ``.list(...)`` return value with ``auto_paging_iter``."""
    m = MagicMock()
    m.auto_paging_iter.return_value = iter(items)
    return m


# ---------------------------------------------------------------------------
# _archive_fixtures — the teardown primitive
# ---------------------------------------------------------------------------


class TestArchiveFixtures:
    def test_archives_only_fixture_products(self) -> None:
        """Real user Products (non-fixture description) must be untouched."""
        fixture = _fake_product("prod_fixture_1")
        real = _fake_product("prod_real", description="")
        prices_for_fixture = [_fake_price("price_fixture_1")]

        with (
            patch("stripe.Product.list") as prod_list,
            patch("stripe.Price.list") as price_list,
            patch("stripe.Price.modify") as price_mod,
            patch("stripe.Product.modify") as prod_mod,
        ):
            prod_list.return_value = _paging([fixture, real])
            price_list.return_value = _paging(prices_for_fixture)

            result = _archive_fixtures("sk_test_abc")

        assert result == {"products": 1, "prices": 1}
        # Only the fixture product + its price were archived.
        prod_mod.assert_called_once_with("prod_fixture_1", active=False)
        price_mod.assert_called_once_with("price_fixture_1", active=False)

    def test_empty_account_is_noop(self) -> None:
        """No products at all → zero archived, no exceptions."""
        with (
            patch("stripe.Product.list") as prod_list,
            patch("stripe.Product.modify") as prod_mod,
            patch("stripe.Price.modify") as price_mod,
        ):
            prod_list.return_value = _paging([])

            result = _archive_fixtures("sk_test_abc")

        assert result == {"products": 0, "prices": 0}
        prod_mod.assert_not_called()
        price_mod.assert_not_called()

    def test_per_row_failure_is_logged_not_fatal(self) -> None:
        """A flaky modify() on one row must not block the rest."""
        fixture_1 = _fake_product("prod_fixture_1")
        fixture_2 = _fake_product("prod_fixture_2")

        def flaky_modify(product_id: str, **kwargs: object) -> None:
            if product_id == "prod_fixture_1":
                raise RuntimeError("network blip")

        with (
            patch("stripe.Product.list") as prod_list,
            patch("stripe.Price.list") as price_list,
            patch("stripe.Product.modify", side_effect=flaky_modify),
            patch("stripe.Price.modify"),
        ):
            prod_list.return_value = _paging([fixture_1, fixture_2])
            price_list.return_value = _paging([])  # no prices on either

            result = _archive_fixtures("sk_test_abc")

        # fixture_2 still gets archived despite fixture_1 failing.
        assert result == {"products": 1, "prices": 0}


# ---------------------------------------------------------------------------
# CLI integration — gates + setup/teardown ordering
# ---------------------------------------------------------------------------


class TestTriggerCommand:
    def test_rejects_live_key(self) -> None:
        """Refuse to run trigger against a ``sk_live_`` key."""
        with (
            patch("shutil.which", return_value="/bin/stripe"),
            secret_settings("STRIPE_SECRET_KEY") as s,
            patch("subprocess.run") as sub,
        ):
            s.STRIPE_SECRET_KEY = "sk_live_real_key_do_not_touch"
            result = invoke(["payment", "trigger", "checkout.session.completed"])

        assert result.exit_code != 0
        assert "live key" in result.output.lower()
        sub.assert_not_called()

    def test_missing_cli_exits_nonzero(self) -> None:
        with patch("shutil.which", return_value=None):
            result = invoke(["payment", "trigger", "checkout.session.completed"])
        assert result.exit_code != 0
        assert "stripe-cli not found" in result.output.lower()

    def test_happy_path_triggers_then_cleans(self) -> None:
        """Setup runs, teardown runs, exit code == trigger's exit code."""
        with (
            patch("shutil.which", return_value="/bin/stripe"),
            secret_settings("STRIPE_SECRET_KEY") as s,
            patch("subprocess.run") as sub,
            patch(
                "app.cli.payment._archive_fixtures",
                return_value={"products": 2, "prices": 2},
            ) as arch,
        ):
            s.STRIPE_SECRET_KEY = "sk_test_fake"
            sub.return_value = SimpleNamespace(returncode=0)

            result = invoke(["payment", "trigger", "checkout.session.completed"])

        assert result.exit_code == 0
        # Setup ran with the test key baked in as --api-key.
        args = sub.call_args[0][0]
        assert args[:4] == ["stripe", "trigger", "--api-key", "sk_test_fake"]
        assert args[-1] == "checkout.session.completed"
        # Teardown ran exactly once.
        arch.assert_called_once_with("sk_test_fake")

    def test_no_cleanup_flag_skips_teardown(self) -> None:
        with (
            patch("shutil.which", return_value="/bin/stripe"),
            secret_settings("STRIPE_SECRET_KEY") as s,
            patch("subprocess.run") as sub,
            patch("app.cli.payment._archive_fixtures") as arch,
        ):
            s.STRIPE_SECRET_KEY = "sk_test_fake"
            sub.return_value = SimpleNamespace(returncode=0)

            result = invoke(
                ["payment", "trigger", "checkout.session.completed", "--no-cleanup"]
            )

        assert result.exit_code == 0
        arch.assert_not_called()
