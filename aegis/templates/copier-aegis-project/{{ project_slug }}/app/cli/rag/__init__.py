"""The ``rag`` command group.

``main.py`` imports this module and reads ``app``, so every command
module must be imported here for its ``@app.command`` decorator to
run. Those imports look unused and are not - they ARE the
registration, which is why the count is asserted in
``tests/cli/test_rag_cli.py``.
"""

from app.cli.rag import collections as collections  # noqa: F401
from app.cli.rag import documents as documents  # noqa: F401
from app.cli.rag import model as model  # noqa: F401
from app.cli.rag import search as search  # noqa: F401
from app.cli.rag.shared import app

__all__ = ["app"]
