"""``ontology``: the app's system model in the formats other tools read
(``app.core.ontology.exports``): the docs' stack page, Backstage's
catalog, a process's OpenTelemetry resource attributes."""

import contextlib
import io
import json
from typing import Annotated

import typer

from app.core.ontology import exports, with_app
from app.core.ontology.model import stack
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
