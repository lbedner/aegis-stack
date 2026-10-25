"""DNS management commands.

Thin wrapper over the ``RegistrarAdapter`` so operators can manage
records on the registered ``BASE_DOMAIN`` without leaving the
terminal. Today this is wired against ``PorkbunAdapter``; when a
Cloudflare / Route53 adapter lands later, this CLI shouldn't need
to change.

Three commands:

- ``dns set <subdomain>`` — create or confirm a record (idempotent).
- ``dns list`` — show every record on the apex domain.
- ``dns delete <subdomain>`` — remove a record by ``(host, type)``.

The default record type is ``A`` and the default IP is read from
``.aegis/deploy.yml`` so most invocations are one positional:

    dns set app                   # A → deploy server IP
    dns set api --ip 1.2.3.4      # explicit override
    dns set assets --type CNAME --content cdn.example.com
"""

from __future__ import annotations

import re
from pathlib import Path

import typer
from app.cli import theme
from app.core.config import settings
from app.services.ops.adapters.porkbun import PorkbunAdapter
from app.services.ops.types import DnsRecord, RetrievedRecord
from rich.table import Table

app = typer.Typer(
    name="dns",
    help="Manage DNS records on the configured BASE_DOMAIN.",
    no_args_is_help=True,
)
console = theme.console()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _resolve_domain(override: str | None) -> str:
    """Return the explicit ``--domain`` or fall back to ``BASE_DOMAIN``."""
    if override:
        return override.strip().lower()
    if not settings.BASE_DOMAIN:
        theme.bad(
            "BASE_DOMAIN is not set. Either set it in .env "
            "(e.g. BASE_DOMAIN=example.com) or pass -d/--domain.",
            err=True,
        )
        raise typer.Exit(1)
    return settings.BASE_DOMAIN.strip().lower()


_DEPLOY_HOST_RE = re.compile(r"^\s*host:\s*['\"]?([^'\"#\s]+)", re.MULTILINE)


def _resolve_default_ip() -> str | None:
    """Return ``server.host`` from the nearest ``.aegis/deploy.yml``, or None.

    Walks up from CWD looking for ``.aegis/deploy.yml`` — same project-
    root convention the rest of the aegis CLI uses.
    """
    here = Path.cwd().resolve()
    for parent in [here, *here.parents]:
        candidate = parent / ".aegis" / "deploy.yml"
        if candidate.is_file():
            try:
                content = candidate.read_text(encoding="utf-8")
            except OSError:
                return None
            match = _DEPLOY_HOST_RE.search(content)
            if match:
                return match.group(1).strip()
            return None
    return None


def _adapter() -> PorkbunAdapter:
    """Build the registrar adapter. One concrete class today; this is
    the seam where a future ``--provider`` switch would live."""
    return PorkbunAdapter()


def _print_records(domain: str, records: list[RetrievedRecord]) -> None:
    """Render the record list as a Rich table on stdout."""
    table = Table(
        title=f"DNS records for {domain}",
        show_lines=False,
        header_style="bold",
    )
    table.add_column("Type", width=8)
    table.add_column("Host")
    table.add_column("Value")
    table.add_column("TTL", justify="right", width=6)
    table.add_column("Prio", justify="right", width=6)
    table.add_column("ID", style="dim", width=12)

    for r in sorted(records, key=lambda r: (r.host, r.type)):
        table.add_row(
            r.type,
            r.host or "@",
            r.value,
            str(r.ttl) if r.ttl else "-",
            str(r.priority) if r.priority is not None else "-",
            r.provider_id or "-",
        )
    console.print(table)


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


@app.command("set")
async def dns_set(
    subdomain: str = typer.Argument(
        ...,
        help=(
            "Subdomain (relative host). Use '@' for the apex. Example: "
            "'app' creates app.<BASE_DOMAIN>."
        ),
    ),
    ip: str | None = typer.Option(
        None,
        "--ip",
        help=(
            "Target IP for an A record. Defaults to the server.host in "
            ".aegis/deploy.yml. Ignored when --type isn't 'A'."
        ),
    ),
    record_type: str = typer.Option(
        "A",
        "--type",
        "-t",
        help="DNS record type (A, CNAME, TXT, MX, ...).",
    ),
    content: str | None = typer.Option(
        None,
        "--content",
        "-c",
        help=(
            "Record value for non-A records (e.g. CNAME target, TXT body, "
            "MX exchange). Required unless --type is 'A'."
        ),
    ),
    ttl: int = typer.Option(
        600,
        "--ttl",
        help="TTL in seconds (Porkbun clamps to a 600 minimum).",
    ),
    priority: int | None = typer.Option(
        None,
        "--priority",
        help="Priority for MX records. Ignored for other types.",
    ),
    domain: str | None = typer.Option(
        None,
        "--domain",
        "-d",
        help="Override BASE_DOMAIN for this call.",
    ),
) -> None:
    """Create (or no-op-confirm) a DNS record. Safe to re-run."""
    apex = _resolve_domain(domain)
    record_type_norm = record_type.strip().upper()
    host = "" if subdomain in ("@", "") else subdomain.strip().lower()

    if record_type_norm == "A":
        value = ip or _resolve_default_ip()
        if not value:
            theme.bad(
                "No IP available. Pass --ip explicitly, or run from a "
                "project with .aegis/deploy.yml present.",
                err=True,
            )
            raise typer.Exit(1)
    else:
        if not content:
            theme.bad(
                f"--content is required for {record_type_norm} records.",
                err=True,
            )
            raise typer.Exit(1)
        value = content

    spec = DnsRecord(
        host=host,
        type=record_type_norm,
        value=value,
        ttl=ttl,
        priority=priority,
    )

    async def _run() -> None:
        adapter = _adapter()
        results = await adapter.create_dns_records(apex, [spec])
        result = results[0]
        label = host or "@"
        if result.provider_id in ("", "(existing)"):
            console.print(
                f"[{theme.WARNING}]reused[/{theme.WARNING}] {record_type_norm} {label} → {value} "
                f"(already on {apex})"
            )
        else:
            console.print(
                f"[{theme.ACCENT}]created[/{theme.ACCENT}] {record_type_norm} {label} → {value} "
                f"on {apex} (id={result.provider_id})"
            )

    await _run()


@app.command("list")
async def dns_list(
    domain: str | None = typer.Option(
        None,
        "--domain",
        "-d",
        help="Override BASE_DOMAIN for this call.",
    ),
    type_filter: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Show only records of this type.",
    ),
) -> None:
    """List every record on the apex domain."""
    apex = _resolve_domain(domain)

    async def _run() -> None:
        adapter = _adapter()
        records = await adapter.list_dns_records(apex)
        if type_filter:
            wanted = type_filter.strip().upper()
            records = [r for r in records if r.type == wanted]
        if not records:
            console.print(f"No records found for {apex}.")
            return
        _print_records(apex, records)

    await _run()


@app.command("delete")
async def dns_delete(
    subdomain: str = typer.Argument(
        ...,
        help="Subdomain to remove. Use '@' for apex.",
    ),
    record_type: str = typer.Option(
        "A",
        "--type",
        "-t",
        help="DNS record type to match.",
    ),
    domain: str | None = typer.Option(
        None,
        "--domain",
        "-d",
        help="Override BASE_DOMAIN for this call.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """Delete the record matching ``(subdomain, type)``.

    If multiple records share the same ``(host, type)`` (uncommon outside
    of MX rotations), removes them all so the post-delete state is
    "no records of that type at that host."
    """
    apex = _resolve_domain(domain)
    host = "" if subdomain in ("@", "") else subdomain.strip().lower()
    record_type_norm = record_type.strip().upper()

    async def _run() -> None:
        adapter = _adapter()
        records = await adapter.list_dns_records(apex)
        matches = [r for r in records if r.host == host and r.type == record_type_norm]
        if not matches:
            console.print(
                f"No {record_type_norm} record for "
                f"{host or '@'}.{apex} — nothing to delete."
            )
            return

        console.print(
            f"About to delete {len(matches)} record(s) for "
            f"[bold]{host or '@'}[/bold] ({record_type_norm}) on {apex}:"
        )
        for r in matches:
            console.print(
                f"  • {r.type} {r.host or '@'} → {r.value} (id={r.provider_id})"
            )
        if not yes:
            confirm = typer.confirm("Proceed?", default=False)
            if not confirm:
                console.print("Aborted.")
                raise typer.Exit(1)

        for r in matches:
            if not r.provider_id:
                console.print(
                    f"[{theme.WARNING}]skipped[/{theme.WARNING}] {r.type} {r.host or '@'} — "
                    "registrar did not return an id"
                )
                continue
            await adapter.delete_dns_record(apex, r.provider_id)
            console.print(
                f"[{theme.ACCENT}]deleted[/{theme.ACCENT}] {r.type} {r.host or '@'} (id={r.provider_id})"
            )

    await _run()
