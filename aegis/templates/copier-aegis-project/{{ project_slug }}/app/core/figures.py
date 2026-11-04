"""How an agent's data is modelled: a field that is not one, or a figure
changed after it was read, is refused. Every model an agent, the API or
Overseer reads takes ``model_config = FIGURES``."""

from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationError

FIGURES = ConfigDict(frozen=True, extra="forbid")


def absent() -> Any:
    """A field an answer leaves out when it does not apply (None), rather
    than hand the reader a null: ``url: str | None = absent()``. The schema
    still names it."""
    return Field(default=None, exclude_if=lambda value: value is None)


def shape_of(schema: type[BaseModel], depth: int = 0) -> str:
    """A schema as the object literal that satisfies it."""
    fields = [
        f"{name}: {_type_name(info.annotation, depth)}"
        for name, info in schema.model_fields.items()
    ]
    return "{" + ", ".join(fields) + "}"


def _type_name(annotation: Any, depth: int) -> str:
    origin = get_origin(annotation)
    if origin is list:
        (inner,) = get_args(annotation)
        return f"[{_type_name(inner, depth + 1)}, ...]"
    if origin in (Union, UnionType):
        return "|".join(_type_name(arg, depth) for arg in get_args(annotation))
    if origin is Literal:
        return "|".join(str(arg) for arg in get_args(annotation))
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return shape_of(annotation, depth + 1) if depth < 2 else annotation.__name__
    if annotation is type(None):
        return "null"
    return getattr(annotation, "__name__", str(annotation))


def misfit(exc: ValidationError, schema: type[BaseModel]) -> str:
    """Why a value an agent sent does not fit ``schema``: every fault at
    once, and the shape that fits, since one at a time is how a wrong
    guess becomes four round trips."""
    faults = "; ".join(
        f"{'.'.join(str(p) for p in err.get('loc', ())) or 'payload'} "
        f"{err.get('msg', 'is invalid')}"
        for err in exc.errors()[:4]
    )
    return f"{faults}. It takes {shape_of(schema)}."
