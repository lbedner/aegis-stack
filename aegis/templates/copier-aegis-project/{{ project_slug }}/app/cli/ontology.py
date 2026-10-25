"""``ontology``: the app's system model in the formats other tools read
(``app.core.ontology.exports``): the docs' stack page, Backstage's
catalog, a process's OpenTelemetry resource attributes. And the twin's
answers from a shell (``find``, ``node``, ``paths``, ``route``): the MCP
``ontology`` tool's, asked as an admin, for a coding agent planning a
change (the plan-with-the-twin skill)."""

import contextlib
import io
import json
from typing import Annotated, Any

import typer

from app.core.ontology import exports, with_app
from app.core.ontology.model import stack
from app.core.tools import acting_as
from app.i18n import lazy_t, t

app = typer.Typer(name="ontology", help=lazy_t("ontology.help"))

FORMATS = ("markdown", "backstage", "otel")


@app.command("export", help=lazy_t("ontology.help_export"))
async def export(
    fmt: Annotated[
        str, typer.Option("--format", help=lazy_t("ontology.opt_format"))
    ] = "markdown",
    owner: Annotated[str, typer.Option(help=lazy_t("ontology.opt_owner"))] = "",
    unit: Annotated[str, typer.Option(help=lazy_t("ontology.opt_unit"))] = "webserver",
) -> None:
    if fmt not in FORMATS:
        raise typer.BadParameter(
            t("ontology.unknown_format", fmt=fmt, formats=", ".join(FORMATS))
        )
    if fmt == "otel":
        typer.echo(json.dumps(exports.otel(stack(), unit), indent=2))
        return
    # Built with the app, so its routes are in it. Building logs to
    # stdout, and the export is read by a program.
    with contextlib.redirect_stdout(io.StringIO()):
        model = with_app()
    typer.echo(
        exports.backstage(model, owner)
        if fmt == "backstage"
        else exports.markdown(model),
        nl=False,
    )


async def _ask(**query: Any) -> None:
    """The ``ontology`` tool's answer to ``query``, as JSON. Built with the
    app, so its routes are in it; building logs to stdout, which a program
    reads, so that is set aside. Asked as an admin: this is the app's own
    shell, as MCP's token or an admin-only socket is."""
    from app.services.system import tools

    with contextlib.redirect_stdout(io.StringIO()):
        with_app()
        with acting_as(None, "cli", admin=True):
            try:
                found = await tools.ontology(**query)
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from None
    typer.echo(json.dumps(found, indent=2, default=str))


@app.command("find", help=lazy_t("ontology.help_find"))
async def find(
    kind: Annotated[str | None, typer.Option(help=lazy_t("ontology.opt_kind"))] = None,
    category: Annotated[
        str | None, typer.Option(help=lazy_t("ontology.opt_category"))
    ] = None,
    text: Annotated[str | None, typer.Option(help=lazy_t("ontology.opt_text"))] = None,
) -> None:
    await _ask(kind=kind, category=category, text=text)


@app.command("node", help=lazy_t("ontology.help_node"))
async def node(
    ids: Annotated[list[str], typer.Argument()],
    depth: Annotated[int, typer.Option(help=lazy_t("ontology.opt_depth"))] = 1,
) -> None:
    await _ask(node=ids if len(ids) > 1 else ids[0], depth=depth)


@app.command("paths", help=lazy_t("ontology.help_paths"))
async def paths(start: str, end: str) -> None:
    await _ask(node=start, to=end)


@app.command("route", help=lazy_t("ontology.help_route"))
async def route(key: str) -> None:
    await _ask(route=key)
