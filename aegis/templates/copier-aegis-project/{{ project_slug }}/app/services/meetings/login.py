"""The bot's Google sign-in: what gets it past Meet's guest check.

Google refuses a sign-in in a browser that automation launched or that has
a debugging port open ("This browser or app may not be secure"). So a
person signs in in a plain Chrome on a fresh profile and quits it; the
profile is then reopened headless to read the login over its debugging
port. It is kept as a secret, where the bot finds it from any process:
``meetings join`` on the host, or the webserver in Docker. Each agent (a
Google account the bot joins as) has its own: the first's is ``LOGIN``,
another's ``LOGIN__<NAME>`` (``domains.accounts``).
"""

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any

from playwright.async_api import async_playwright

from app.core import secrets
from app.core.secrets import Secret

LOGIN = "MEETINGS_BOT_LOGIN_SECRET"
SECRETS = (
    Secret(LOGIN, owner="Meetings", label="The bot's Google sign-in", family=True),
)

SIGN_IN_URL = "https://accounts.google.com/"
# Google's session cookie: there once the sign-in is finished.
SESSION_COOKIE = "SID"
CHROMES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
)
# How long Chrome gets to open its debugging port.
START_SECONDS = 15


class LoginError(RuntimeError):
    """Chrome could not be started, or nobody signed in."""


async def stored_login(secret: str = LOGIN) -> dict[str, Any] | None:
    """The sign-in kept as ``secret`` (Playwright's ``storage_state``), None
    until one is."""
    value = await secrets.get(secret)
    return json.loads(value) if value else None


def find_chrome() -> str | None:
    """The first Chrome on this machine, by path or on ``PATH``."""
    for chrome in CHROMES:
        found = chrome if Path(chrome).exists() else shutil.which(chrome)
        if found:
            return found
    return None


async def capture_login(chrome: str) -> dict[str, Any]:
    """Chrome at Google's sign-in, until the person quits it; then the
    login it kept. Raises LoginError when nobody signed in."""
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            _chrome(chrome, profile, SIGN_IN_URL),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        with _debugging(chrome, Path(profile)) as address:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(address)
                state = await browser.contexts[0].storage_state()
    if not signed_in(state):
        raise LoginError("No Google sign-in in that Chrome: finish it before quitting.")
    return state


async def save_login(state: dict[str, Any], actor: str, secret: str = LOGIN) -> None:
    await secrets.put(secret, json.dumps(state), actor)


def signed_in(state: dict[str, Any], now: float | None = None) -> bool:
    """Whether ``state`` holds Google's session; with ``now`` (epoch
    seconds), one that has not expired by then (-1: when Chrome closes)."""
    return any(
        cookie["name"] == SESSION_COOKIE
        and cookie["domain"].endswith("google.com")
        and (now is None or not 0 <= cookie.get("expires", -1) <= now)
        for cookie in state["cookies"]
    )


def _chrome(chrome: str, profile: str | Path, *flags: str) -> list[str]:
    """Chrome on ``profile``, the same profile both times it opens."""
    return [
        chrome,
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        *flags,
    ]


@contextmanager
def _debugging(chrome: str, profile: Path) -> Iterator[str]:
    """``profile`` reopened headless with a debugging port, yielding its
    address; closed on exit."""
    process = subprocess.Popen(
        _chrome(chrome, profile, "--headless=new", "--remote-debugging-port=0"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield f"http://127.0.0.1:{_debugging_port(profile, process)}"
    finally:
        process.terminate()
        process.wait()


def _debugging_port(profile: Path, process: subprocess.Popen[bytes]) -> str:
    """The port Chrome picked, which it writes into its profile."""
    written = profile / "DevToolsActivePort"
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LoginError(f"Chrome exited (code {process.returncode}).")
        if written.exists() and (port := written.read_text().split("\n")[0]):
            return port
        time.sleep(0.2)
    raise LoginError(f"Chrome did not open its debugging port in {START_SECONDS}s.")
