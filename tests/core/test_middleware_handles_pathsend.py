"""Body-rewriting middleware must handle ``http.response.pathsend``.

Granian advertises the extension and uvicorn does not, so a server that
offers it hands middleware a file *path* instead of a response body for
static files. Middleware that buffers ``http.response.body`` and ignores
``http.response.pathsend`` forwards a body with no start, and every
affected page returns 500. That is not hypothetical: it is what happened
to the dashboard the first time the app was served under granian.

Documenting the contract is the weak version of this. Enforcing it over
the middleware Aegis ships is the strong one, and it is the half Aegis
actually owns. User middleware is still on the user, which is why the
docs say so as well.
"""

from __future__ import annotations

import ast
from pathlib import Path

MIDDLEWARE_DIR = (
    Path(__file__).parent.parent.parent
    / "aegis/templates/copier-aegis-project/{{ project_slug }}"
    / "app/components/backend/middleware"
)

BODY = "http.response.body"
PATHSEND = "http.response.pathsend"


def _string_constants(path: Path) -> set[str]:
    """Every string literal in a module, Jinja tags tolerated."""
    source = path.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # A .jinja template is not valid Python until rendered; fall back
        # to a substring check rather than skipping the file entirely.
        return {BODY, PATHSEND} & {
            token for token in (BODY, PATHSEND) if token in source
        }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_body_buffering_middleware_also_handles_pathsend() -> None:
    offenders = []
    for path in sorted(MIDDLEWARE_DIR.glob("*.py*")):
        constants = _string_constants(path)
        if BODY in constants and PATHSEND not in constants:
            offenders.append(path.name)

    assert not offenders, (
        "These middleware modules touch http.response.body but never "
        f"http.response.pathsend: {', '.join(offenders)}. Under granian "
        "they will forward a body with no start and 500 the page. Handle "
        "the pathsend message, or pass the response through untouched."
    )
