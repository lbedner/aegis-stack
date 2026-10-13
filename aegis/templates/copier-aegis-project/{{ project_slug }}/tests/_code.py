"""Code that looks like it lives somewhere it does not: a function whose
frames say ``app/services/ai/talk.py``, for what reads where code is
(log attribution, ``edges``' callers)."""

from collections.abc import Callable
from typing import Any


def function_at(path: str, source: str, **scope: Any) -> Callable[..., Any]:
    """``def run(): <source>``, compiled as though from ``path``; ``scope``
    is what its source may name."""
    namespace: dict[str, Any] = dict(scope)
    exec(compile("def run():\n" + source, path, "exec"), namespace)
    return namespace["run"]
