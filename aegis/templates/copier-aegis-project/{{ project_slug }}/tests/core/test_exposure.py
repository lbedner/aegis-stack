"""Whether Overseer shows the app's own source or data (``exposure.shown``):
in dev; elsewhere once an admin turns it on, and with no one to sign in only
on the build that was never deployed, so turning it on publishes nothing."""

import pytest

from app.core import exposure
from app.core.config import settings

FLAG = exposure.CODE


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "BUILD_ID", "abc123")
    monkeypatch.setitem(settings.__dict__, FLAG, False)
    return monkeypatch


def test_dev_shows_it() -> None:
    assert settings.is_dev and exposure.shown(FLAG)


def test_outside_dev_it_waits_to_be_turned_on(deployed: pytest.MonkeyPatch) -> None:
    deployed.setattr(settings, "AUTH_ENABLED", True)
    assert not exposure.shown(FLAG)
    deployed.setitem(settings.__dict__, FLAG, True)
    assert exposure.shown(FLAG)


def test_with_no_one_to_sign_in_a_deployed_build_never_shows_it(
    deployed: pytest.MonkeyPatch,
) -> None:
    """Without auth, Overseer is anyone's to read: the setting would put
    the app on the open internet, so only the undeployed build honours it."""
    deployed.setattr(settings, "AUTH_ENABLED", False)
    deployed.setitem(settings.__dict__, FLAG, True)
    assert not exposure.shown(FLAG)
    deployed.setattr(settings, "BUILD_ID", exposure.LOCAL)
    assert exposure.shown(FLAG)


def test_a_refusal_says_what_would_show_it(deployed: pytest.MonkeyPatch) -> None:
    """With an admin, turning the flag on; with no one to sign in on a
    deployed build, the flag would do nothing, so it says to add auth."""
    deployed.setattr(settings, "AUTH_ENABLED", True)
    assert FLAG in (exposure.refusal(FLAG) or "")
    deployed.setattr(settings, "AUTH_ENABLED", False)
    deployed.setitem(settings.__dict__, FLAG, True)
    assert "aegis add auth" in (exposure.refusal(FLAG) or "")


def test_deployed_is_any_build_a_deploy_stamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BUILD_ID", exposure.LOCAL)
    assert not exposure.deployed()
    monkeypatch.setattr(settings, "BUILD_ID", "abc123")
    assert exposure.deployed()
