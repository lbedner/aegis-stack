"""Settings saved in the Overseer: the ``Configurable`` fields of
``Settings``.

They are declared to ``app.core.secrets`` as plain entries
(``secret=False``) marked ``setting``, so the same store, rules and
surfaces carry them: the secrets component's table keeps a saved value,
``.env`` wins and reads as read-only, every write is audited. What differs
is when a value takes effect. Code reads these through ``settings``, so
``apply_saved`` loads them into it as each process starts
(``app.core.boot``): a saved value applies on the next restart.
"""

from collections.abc import Awaitable, Callable
from enum import Enum
from functools import cache, partial
from typing import Any, Literal, get_args, get_origin

from pydantic import TypeAdapter, ValidationError
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from app.core import secrets
from app.core.config import settings
from app.core.configurable import Configurable
from app.core.log import logger

# What a setting's save or reset says (``.format(name=...)``).
SAVED = "{name} saved; it applies when the app restarts"
RESET = "{name} goes back to its default on restart"

# What ``.env`` and the environment set, read before anything is applied: a
# field missing from it is at its default, so a saved value may replace it.
IN_ENV: frozenset[str] = frozenset(settings.model_fields_set)


@cache
def _marked() -> dict[str, tuple[FieldInfo, Configurable]]:
    """Every ``Configurable`` field with its marker: declarations are code."""
    found = {}
    for name, field in type(settings).model_fields.items():
        marker = next((m for m in field.metadata if isinstance(m, Configurable)), None)
        if marker is not None:
            found[name] = (field, marker)
    return found


def left_at_default() -> frozenset[str]:
    """The settings ``.env`` does not set: a saved value applies to these."""
    return frozenset(name for name in _marked() if name not in IN_ENV)


def saved(name: str, result: str | None = None, detail: str = "") -> str:
    """What every surface says once a value is saved: a setting applies on
    restart; a key names its check's ``result``, when it had one."""
    if secrets.is_setting(name):
        return SAVED.format(name=name)
    if result is None:
        return f"{name} saved"
    word = "verified" if result == secrets.VERIFIED else "not verified"
    return f"{name} saved, {word}. {detail}"


def removed(name: str) -> str:
    """What every surface says once a stored value is removed."""
    return (RESET if secrets.is_setting(name) else "{name} removed").format(name=name)


def options(name: str) -> list[str] | None:
    """The values the setting may take, when it is a closed set: the
    marker's ``choices``, else a ``bool``, ``Literal`` or ``Enum`` type."""
    field, marker = _marked()[name]
    kind = field.annotation
    if marker.choices is not None:
        # Empty (no timezone data on this system, say) restricts nothing.
        return [str(choice) for choice in marker.choices()] or None
    if kind is bool:
        return ["True", "False"]
    if get_origin(kind) is Literal:
        return [str(arg) for arg in get_args(kind)]
    if isinstance(kind, type) and issubclass(kind, Enum):
        return [str(member.value) for member in kind]
    return None


def _text(value: Any) -> str:
    return str(value.value if isinstance(value, Enum) else value)


def coerce(name: str, value: str) -> Any:
    """``value`` as the setting's type, or ``SecretRejectedError`` saying
    why it does not fit the type or, for a closed set, its values."""
    field, _ = _marked()[name]
    try:
        # With its bounds (``Field(ge=...)``), not only its type: the
        # code that reads it may refuse what the type allows.
        typed = TypeAdapter(field.rebuild_annotation()).validate_python(value)
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"]
        raise secrets.SecretRejectedError(
            f"{value!r} is not valid: {reason}."
        ) from None
    allowed = options(name)
    if allowed is not None and _text(typed) not in allowed:
        raise secrets.SecretRejectedError(f"{value!r} is not one of its choices.")
    return typed


def parse(name: str, value: str) -> str:
    """The text to store for ``value`` (``coerce``d): one spelling, ``true``
    keeps as ``True``, so a stored value matches its choice."""
    return _text(coerce(name, value))


def _offer(name: str) -> Callable[[], Awaitable[list[tuple[str, str]]]] | None:
    allowed = options(name)
    if allowed is None:
        return None

    async def offered() -> list[tuple[str, str]]:
        return [(value, value) for value in allowed]

    return offered


def default_of(name: str) -> Any:
    """The field's own default (a factory's, called)."""
    field, _ = _marked()[name]
    value = field.get_default(call_default_factory=True, validated_data={})
    return None if value is PydanticUndefined else value


def owners() -> set[str]:
    """The keys of the components and services this stack has settings for."""
    return {marker.owner for _, marker in _marked().values()}


def declarations() -> list[secrets.Secret]:
    """The settings, as ``app.core.secrets`` lists and stores them, each
    under its owner's name (``get_component_title``)."""
    from app.services.system.ui import get_component_title

    return [
        secrets.Secret(
            name,
            owner=get_component_title(marker.owner),
            label=marker.label or field.description or "",
            secret=False,
            setting=True,
            default=None if default_of(name) is None else _text(default_of(name)),
            parse=partial(parse, name),
            choices=_offer(name),
        )
        for name, (field, marker) in _marked().items()
    ]


async def apply_saved() -> list[str]:
    """Load saved values into ``settings``; the names applied. A setting in
    ``.env`` keeps that value, and a saved value that no longer fits its
    type (the field changed) is skipped and logged."""
    names = sorted(left_at_default())
    if not names or secrets.store_name() is None:
        return []
    applied = []
    for name, raw in (await secrets.get_many(*names)).items():
        if raw is None:
            continue
        try:
            value = coerce(name, raw)
        except secrets.SecretRejectedError as exc:
            logger.warning("Saved setting skipped", name=name, reason=str(exc))
            continue
        setattr(settings, name, value)
        applied.append(name)
    return applied
