"""What ``aegis deploy`` prints when it finishes points somewhere that answers.

After ``deploy-provision`` the app is reached at its provisioned name, not
the bare IP. Traefik admits only private networks to the Overseer until
``ADMIN_IP_ALLOWLIST`` is set, so a live run printed an Overseer link that
could only ever answer 403.
"""

import re
from pathlib import Path

import pytest

from aegis.commands import deploy

HOST = "203.0.113.7"


def _urls(text: str) -> list[str]:
    """Every URL in the output, whole: compared exactly, never by substring."""
    return re.findall(r"https?://[^\s)]+", text)


def test_the_provisioned_name_wins_over_the_ip(
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {"server": {"host": HOST}, "domain": "203-0-113-7.sslip.io"}

    deploy._print_deployed(config, allowlist_set=True)

    out = capsys.readouterr().out
    assert _urls(out) == [
        "http://203-0-113-7.sslip.io",
        "http://203-0-113-7.sslip.io/dashboard/",
    ]
    assert HOST not in out


def test_without_a_name_the_host_is_used(capsys: pytest.CaptureFixture[str]) -> None:
    deploy._print_deployed({"server": {"host": HOST}}, allowlist_set=True)

    assert _urls(capsys.readouterr().out)[0] == f"http://{HOST}"


@pytest.mark.parametrize("allowlist_set", [True, False])
def test_the_allowlist_hint_shows_until_the_allowlist_is_set(
    allowlist_set: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    deploy._print_deployed({"server": {"host": HOST}}, allowlist_set=allowlist_set)

    assert ("ADMIN_IP_ALLOWLIST" in capsys.readouterr().out) is not allowlist_set


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({".env": "ADMIN_IP_ALLOWLIST=198.51.100.4/32\n"}, True),
        ({".env": "# ADMIN_IP_ALLOWLIST=198.51.100.4/32\n"}, False),
        ({".env": "ADMIN_IP_ALLOWLIST=\n"}, False),
        # .env.deploy is the file a deploy ships when both exist.
        (
            {".env": "ADMIN_IP_ALLOWLIST=0.0.0.0/0\n", ".env.deploy": "PORT=8000\n"},
            False,
        ),
        ({}, False),
    ],
)
def test_the_allowlist_is_read_from_the_file_a_deploy_ships(
    tmp_path: Path, files: dict[str, str], expected: bool
) -> None:
    for name, body in files.items():
        (tmp_path / name).write_text(body)

    assert deploy._admin_allowlist_set(tmp_path) is expected


def test_with_tls_the_links_are_https(capsys: pytest.CaptureFixture[str]) -> None:
    config = {"server": {"host": HOST}, "domain": "203-0-113-7.sslip.io"}

    deploy._print_deployed(config, allowlist_set=True, tls=True)

    out = capsys.readouterr().out
    assert _urls(out) == [
        "https://203-0-113-7.sslip.io",
        "https://203-0-113-7.sslip.io/dashboard/",
    ]


def test_with_tls_the_health_check_goes_through_https_for_the_name() -> None:
    """Port 80 redirects to HTTPS, and curl without -L passes on the redirect."""
    command = deploy._health_check_command("203-0-113-7.sslip.io", tls=True)

    assert _urls(command) == ["https://203-0-113-7.sslip.io/health/"]
    assert "--resolve 203-0-113-7.sslip.io:443:127.0.0.1" in command


def test_without_tls_the_health_check_is_plain_http() -> None:
    assert _urls(deploy._health_check_command(None, tls=False)) == [
        "http://localhost/health/"
    ]


@pytest.mark.parametrize("answers", [None, "{not: [valid yaml", "author_email: x\n"])
def test_a_missing_or_corrupt_answers_file_reads_as_no_answers(
    tmp_path: Path, answers: str | None
) -> None:
    """The neon check always tolerated it; the TLS lookup crashed the deploy."""
    if answers is not None:
        (tmp_path / ".copier-answers.yml").write_text(answers)

    name, tls = deploy._public_address({"server": {"host": HOST}}, tmp_path)

    assert (name, tls) == (None, False)
    assert deploy._is_neon_database(str(tmp_path)) is False


def test_the_name_traefik_routes_on_wins_over_the_provisioned_one(
    tmp_path: Path,
) -> None:
    """After ``ingress-enable --domain`` the router matches ``ingress_domain``;
    checking health on the old provisioned name gets a 404 and a rollback."""
    (tmp_path / ".copier-answers.yml").write_text(
        "ingress_tls: true\ningress_domain: app.example.org\n"
    )

    name, _ = deploy._public_address({"domain": "203-0-113-7.sslip.io"}, tmp_path)

    assert name == "app.example.org"
