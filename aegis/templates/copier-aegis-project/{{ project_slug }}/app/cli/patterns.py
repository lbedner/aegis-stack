"""``patterns``: the app's patterns and macro catalog as a brief.

The same report the Overseer's Patterns page renders, printed for an
agent (or a person) to read before building: each pattern's steps, its
rules with their reasons and every violation, the canonical example's
source, and every instance; then the shared macros with their examples.
Markdown by default, JSON with ``--format json``.
"""

import contextlib
import io
import json
from typing import Annotated, Any

import typer

from app.i18n import lazy_t
from app.services.system import patterns

app = typer.Typer(
    name="patterns", help=lazy_t("patterns.help"), invoke_without_command=True
)


def _routes() -> list[Any]:
    from app.integrations.main import create_integrated_app

    return list(create_integrated_app().routes)


def _pattern(report: patterns.Report) -> dict[str, Any]:
    pattern = report.pattern
    titles = {rule.key: rule.title for rule in pattern.rules}
    canonical = None
    if report.canonical is not None:
        code, path = patterns.source(pattern.function(report.canonical.target))
        canonical = {"label": report.canonical.label, "file": path, "source": code}
    return {
        "key": pattern.key,
        "title": pattern.title,
        "summary": pattern.summary,
        "steps": [s._asdict() for s in report.steps],
        "rules": [
            {
                "key": r.key,
                "title": r.title,
                "why": r.why,
                "enforced": r.enforced,
                "followed": r.followed,
                "applicable": r.applicable,
                "violations": [i.label for i in r.violations],
            }
            for r in report.rules
        ],
        "canonical": canonical,
        "instances": [
            {"label": i.label, "findings": [titles[k] for k in i.findings]}
            for i in report.instances
        ],
    }


def _macros() -> list[dict[str, Any]] | None:
    """The macro catalog, when the project has the web frontend."""
    try:
        from app.components.web_frontend import macro_catalog
    except ImportError:
        return None
    return [
        {
            "file": path,
            "macros": [
                {
                    "name": m.name,
                    "signature": m.signature,
                    "doc": m.doc,
                    "example": m.example,
                }
                for m in macro_catalog.catalog(section)
            ],
        }
        for section, path in macro_catalog.FILES.items()
    ]


def collect() -> dict[str, Any]:
    """Every installed pattern's report, and the macros if there are any."""
    routes = _routes()
    brief: dict[str, Any] = {
        "patterns": [
            _pattern(patterns.report(p, routes))
            for p in patterns.installed_patterns().values()
        ]
    }
    macros = _macros()
    if macros is not None:
        brief["macros"] = macros
    return brief


def _pattern_markdown(p: dict[str, Any]) -> list[str]:
    lines = [f"## {p['title']}", "", p["summary"], "", "### Steps", ""]
    for step in p["steps"]:
        count = ""
        if step["followed"] is not None:
            count = f" ({step['followed']} of {step['applicable']} follow)"
        lines.append(f"1. **{step['label']}**: {step['detail']}{count}")
    lines += ["", "### Rules", ""]
    for rule in p["rules"]:
        kind = "enforced" if rule["enforced"] else "advisory"
        lines.append(
            f"- **{rule['title']}** ({kind}, {rule['followed']} of "
            f"{rule['applicable']} follow): {rule['why']}"
        )
        lines += [f"  - breaks it: `{label}`" for label in rule["violations"]]
    if p["canonical"]:
        c = p["canonical"]
        lines += [
            "",
            f"### Canonical example: `{c['label']}`",
            "",
            f"From `{c['file']}`:",
        ]
        lines += ["", "```python", c["source"].rstrip(), "```"]
    lines += ["", f"### Instances ({len(p['instances'])})", ""]
    for i in p["instances"]:
        note = f" ({', '.join(i['findings'])})" if i["findings"] else ""
        lines.append(f"- `{i['label']}`{note}")
    return [*lines, ""]


def _macros_markdown(groups: list[dict[str, Any]]) -> list[str]:
    lines = ["## Frontend macros", ""]
    for group in groups:
        lines += [f"### `{group['file']}`", ""]
        for m in group["macros"]:
            lines += [f"#### `{m['signature']}`", ""]
            if m["doc"]:
                lines += [m["doc"], ""]
            lines += ["```jinja", m["example"], "```", ""]
    return lines


def markdown(brief: dict[str, Any]) -> str:
    lines = [
        "# Patterns",
        "",
        "How this app is built, detected from its code. Follow the canonical "
        "examples; the rules say why.",
        "",
    ]
    for p in brief["patterns"]:
        lines += _pattern_markdown(p)
    if "macros" in brief:
        lines += _macros_markdown(brief["macros"])
    return "\n".join(lines)


@app.callback(help=lazy_t("patterns.help_show"))
def show(
    fmt: Annotated[
        str,
        typer.Option("--format", help=lazy_t("patterns.opt_format")),
    ] = "markdown",
) -> None:
    # Building the app and loading the queues log to stdout; that noise is
    # kept out of a report meant to be read by a program.
    with contextlib.redirect_stdout(io.StringIO()):
        brief = collect()
    typer.echo(json.dumps(brief, indent=2) if fmt == "json" else markdown(brief))
