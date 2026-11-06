"""DNS management commands, on ``app.services.ops.dns`` (the domain, the
registrar, a record from what was typed), as Overseer > Deployments > DNS.

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

from rich.table import Table
import typer

from app.cli import theme
from app.services.ops import dns
from app.services.ops.types import RetrievedRecord

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
    apex = dns.domain()
    if not apex:
        theme.bad(
            "BASE_DOMAIN is not set. Either set it in .env "
            "(e.g. BASE_DOMAIN=example.com) or pass -d/--domain.",
            err=True,
        )
        raise typer.Exit(1)
    return apex


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
        shown = dns.fields(r)
        table.add_row(
            shown["type"],
            shown["host"],
            shown["value"],
            shown["ttl"] if r.ttl else "-",
            shown["priority"] or "-",
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
        dns.TTL,
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
    try:
        value = ip if record_type.strip().upper() == "A" else content
        spec = dns.record(subdomain, record_type, value, ttl, priority)
    except ValueError as exc:
        theme.bad(str(exc), err=True)
        raise typer.Exit(1) from None

    async def _run() -> None:
        adapter = dns.registrar()
        results = await adapter.create_dns_records(apex, [spec])
        result = results[0]
        said = f"{spec.type} {spec.host or '@'} → {spec.value}"
        if result.provider_id in ("", "(existing)"):
            console.print(
                f"[{theme.WARNING}]reused[/{theme.WARNING}] {said} (already on {apex})"
            )
        else:
            console.print(
                f"[{theme.ACCENT}]created[/{theme.ACCENT}] {said} "
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
        adapter = dns.registrar()
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
    host = dns.host(subdomain)
    record_type_norm = record_type.strip().upper()

    async def _run() -> None:
        adapter = dns.registrar()
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
