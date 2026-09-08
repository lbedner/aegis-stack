"""
Generic option specification + bracket-syntax parser.

R3 of the plugin system refactor. Replaces the per-service parsers
(``ai_service_parser.py``, ``auth_service_parser.py``,
``insights_service_parser.py``) with a single declarative model that
any ``PluginSpec`` can use.

A spec declares its options as ``options: list[OptionSpec]`` on the
``PluginSpec``. The generic ``parse_options(spec_str, plugin_spec)``
parses ``name[opt1,opt2]`` syntax into a ``dict`` keyed by option name,
applying defaults for any option not specified in the bracket content.

Each option declares a ``mode``:

* ``SINGLE`` — at most one value; default is a single string (or ``None``).
* ``MULTI``  — multiple values allowed; default is a list of strings.
* ``FLAG``   — boolean toggle; present in brackets means ``True``; default
  is ``False``.

Options can also declare an ``auto_requires`` callable: given the parsed
value, return a list of component names to auto-add to the spec's
required set. This replaces the hard-coded "AI auto-adds database when
backend != memory" / "auth replaces database with database[engine]"
branches in ``service_resolver.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class OptionMode(Enum):
    """How an option's bracket-content values map to a parsed value."""

    SINGLE = "single"
    """At most one value from ``choices``. Multiple = error."""

    MULTI = "multi"
    """Any subset of ``choices``. Duplicates = error."""

    FLAG = "flag"
    """Boolean toggle; present in brackets means True, absent means False (or default)."""


@dataclass
class OptionSpec:
    """One bracket-syntax option declared on a ``PluginSpec``.

    The option's ``choices`` define the membership test used to categorise
    bracket values into options — every option's choices must be disjoint
    from the others on the same spec, since the parser categorises
    untagged values by membership.
    """

    name: str
    """Key under which the parsed value appears in the result dict."""

    mode: OptionMode
    """How values are accumulated. See ``OptionMode``."""

    choices: list[str]
    """Valid values for this option. The parser uses these for membership."""

    default: Any = None
    """Default value applied when the option is not present in the brackets.
    Conventions: ``str`` for SINGLE, ``list[str]`` for MULTI, ``bool`` (False) for FLAG.
    SINGLE may also use ``None`` to mean "no value picked"."""

    auto_requires: Callable[[Any], list[str]] | None = None
    """Optional rule: given the parsed value, return components to auto-add.

    Example (AI ``backend`` option)::

        auto_requires=lambda v: [f"database[{v}]"] if v != "memory" else []
    """

    answer_key: str | None = None
    """Where this option's chosen value lives in the project's answers
    (``auth_level``, ``ai_framework``). Set only on SINGLE options whose
    value is project-wide state; it is what lets a dependency such as
    ``auth[org]`` be compared against what the project already has."""

    ordered: bool = False
    """``choices`` are ascending levels (auth: basic < rbac < org). A
    request at or below the project's current value is satisfied; above
    it is an upgrade. Unordered options treat any mismatch as a conflict."""


# ---------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------


def is_spec_with_options(spec_str: str) -> bool:
    """True iff ``spec_str`` uses bracket syntax (e.g. ``ai[sqlite]``)."""
    return "[" in spec_str.strip()


def _bracket_content(spec_str: str, base_name: str) -> str | None:
    """Return the inside-of-brackets content, or ``None`` if no brackets.

    Raises ``ValueError`` on malformed brackets.
    """
    s = spec_str.strip()
    if s == base_name:
        return None
    if not s.startswith(f"{base_name}["):
        raise ValueError(
            f"Invalid spec string '{spec_str}'. "
            f"Expected '{base_name}' or '{base_name}[options]' format."
        )
    if not s.endswith("]"):
        raise ValueError(f"Malformed brackets in '{spec_str}'. Expected closing ']'.")
    return s[len(base_name) + 1 : -1].strip()


def parse_options(spec_str: str, plugin_spec: Any) -> dict[str, Any]:
    """Parse ``name[opt1,opt2,...]`` against a plugin spec's option list.

    Returns a dict mapping each option's ``name`` to its parsed value:

    * SINGLE: ``str`` (the matched choice, or ``option.default``)
    * MULTI:  ``list[str]`` (matched choices in input order, deduped, or
      ``option.default``)
    * FLAG:   ``bool`` (``True`` if present, else ``option.default or False``)

    Args:
        spec_str: The spec string from the user, like ``"ai[sqlite,openai]"``.
        plugin_spec: A ``PluginSpec`` whose ``options`` list drives parsing.
            Pass the spec object (not just the options) so error messages
            can quote the spec name.

    Raises:
        ValueError: on unknown values, duplicate single-select, or malformed
            bracket structure.
    """
    options: list[OptionSpec] = list(getattr(plugin_spec, "options", []) or [])
    base_name = plugin_spec.name

    # Initialise result with defaults
    result: dict[str, Any] = {}
    for opt in options:
        if opt.mode is OptionMode.MULTI:
            result[opt.name] = list(opt.default) if opt.default is not None else []
        elif opt.mode is OptionMode.FLAG:
            result[opt.name] = bool(opt.default) if opt.default is not None else False
        else:  # SINGLE
            result[opt.name] = opt.default

    content = _bracket_content(spec_str, base_name)
    if content is None or content == "":
        # No brackets, or empty brackets: defaults apply.
        return result

    # Bracket values are case-insensitive (matches the pre-R3 auth /
    # insights behaviour; safe for AI since its choices are already
    # lowercase).
    values = _bracket_values(content)

    # Track per-option occurrences (so we can reject duplicates in SINGLE
    # and duplicates in MULTI / FLAG).
    matches_per_option: dict[str, list[str]] = {opt.name: [] for opt in options}

    for value in values:
        match = _find_option_for_value(value, options)
        if match is None:
            raise ValueError(_unknown_value_message(value, base_name, options))
        matches_per_option[match.name].append(value)

    for opt in options:
        matches = matches_per_option[opt.name]
        if not matches:
            continue

        if opt.mode is OptionMode.SINGLE:
            if len(matches) > 1:
                raise ValueError(
                    f"Cannot specify multiple values for '{opt.name}' in "
                    f"{base_name}[...]: {', '.join(matches)}. "
                    f"Choose one of: {', '.join(sorted(opt.choices))}."
                )
            result[opt.name] = matches[0]
        elif opt.mode is OptionMode.MULTI:
            if len(matches) != len(set(matches)):
                duplicates = sorted({m for m in matches if matches.count(m) > 1})
                raise ValueError(
                    f"Duplicate value(s) for '{opt.name}' in "
                    f"{base_name}[...]: {', '.join(duplicates)}."
                )
            # Preserve user-supplied order, no surprise re-sort.
            result[opt.name] = list(matches)
        else:  # FLAG
            # Flags are presence/absence; multiple identical flags = duplicate
            # typo, reject the same way duplicate single-selects are rejected.
            if len(matches) > 1:
                raise ValueError(
                    f"Duplicate flag '{opt.name}' in {base_name}[...]: "
                    f"appeared {len(matches)} times."
                )
            result[opt.name] = True

    return result


class VariantConflictError(ValueError):
    """A bracket request names a value the project holds differently on an
    unordered option (``ai[langchain]`` on a pydantic-ai project). Never
    swapped silently: the caller reports it."""


def _bracket_values(content: str) -> list[str]:
    """Bracket content split into normalised values (case-insensitive,
    matching the pre-R3 auth / insights behaviour)."""
    return [v.strip().lower() for v in content.split(",") if v.strip()]


def variant_answers(spec_str: str, plugin_spec: Any) -> dict[str, Any]:
    """The answers a request such as ``auth[org]`` names: ``{answer_key:
    value}`` for every option spelled out in the brackets that maps to an
    answer. A bare name, or a flag with no ``answer_key``, names nothing.
    This is what a fresh install applies; it looks at nothing the project
    already holds (copier records defaults such as ``ai_backend: memory``
    even for services that are not installed, so comparing there would
    invent conflicts).
    """
    options: list[OptionSpec] = list(getattr(plugin_spec, "options", []) or [])
    content = _bracket_content(spec_str, plugin_spec.name)
    if not content or not options:
        return {}
    parsed = parse_options(spec_str, plugin_spec)
    explicit = {
        opt.name
        for value in _bracket_values(content)
        if (opt := _find_option_for_value(value, options)) is not None
    }
    return {
        opt.answer_key: parsed[opt.name]
        for opt in options
        if opt.name in explicit
        and opt.answer_key is not None
        and opt.mode is OptionMode.SINGLE
    }


def variant_delta(
    spec_str: str, plugin_spec: Any, answers: dict[str, Any]
) -> dict[str, Any]:
    """Answers a request such as ``auth[org]`` would still change on a
    project that HAS the service: :func:`variant_answers` filtered through
    :func:`answers_delta`."""
    return answers_delta(plugin_spec, variant_answers(spec_str, plugin_spec), answers)


def answers_delta(
    plugin_spec: Any, requested: dict[str, Any], answers: dict[str, Any]
) -> dict[str, Any]:
    """The subset of ``requested`` (``{answer_key: value}``) the project's
    answers do not already satisfy.

    An answer that is missing or not one of the option's choices is
    treated as unset. Ordered options are satisfied by any current value
    at or above the request; unordered ones raise
    :class:`VariantConflictError` on a mismatch. Shared by the resolver,
    ``add-service`` and ``ManualUpdater``, so a downgrade request is
    "already satisfied" everywhere and never rewrites a level.
    """
    by_key = {
        opt.answer_key: opt
        for opt in (getattr(plugin_spec, "options", []) or [])
        if opt.answer_key is not None
    }
    delta: dict[str, Any] = {}
    for key, wanted in requested.items():
        opt = by_key.get(key)
        if opt is None:
            continue
        current = answers.get(key)
        if current not in opt.choices:
            delta[key] = wanted
        elif opt.ordered:
            if opt.choices.index(wanted) > opt.choices.index(current):
                delta[key] = wanted
        elif current != wanted:
            raise VariantConflictError(
                f"{plugin_spec.name}[{wanted}] conflicts with the project's "
                f"{key}={current!r}; change it deliberately rather than "
                "through a dependency"
            )
    return delta


def variant_answer_keys(plugin_spec: Any) -> list[str]:
    """The answer keys a spec's options map to, in declaration order."""
    return [
        opt.answer_key
        for opt in (getattr(plugin_spec, "options", []) or [])
        if opt.answer_key is not None
    ]


def _find_option_for_value(value: str, options: list[OptionSpec]) -> OptionSpec | None:
    """Return the OptionSpec that lists ``value`` in its choices, or None."""
    for opt in options:
        if value in opt.choices:
            return opt
    return None


def _unknown_value_message(
    value: str, base_name: str, options: list[OptionSpec]
) -> str:
    """Build a human-readable error listing each option's valid choices."""
    parts = [f"Unknown value '{value}' in {base_name}[...] syntax."]
    for opt in options:
        parts.append(f"Valid {opt.name}: {', '.join(sorted(opt.choices))}.")
    return " ".join(parts)


# ---------------------------------------------------------------------
# Auto-requires
# ---------------------------------------------------------------------


def compute_auto_requires(plugin_spec: Any, parsed: dict[str, Any]) -> list[str]:
    """Apply each option's ``auto_requires`` lambda to the parsed values.

    Returns a flat list of component names to add to the spec's required set.
    Caller is responsible for merging + bracket-variant normalisation
    (i.e. dropping plain ``database`` if ``database[postgres]`` is also present).
    """
    extras: list[str] = []
    options: list[OptionSpec] = list(getattr(plugin_spec, "options", []) or [])
    for opt in options:
        if opt.auto_requires is None:
            continue
        if opt.name not in parsed:
            continue
        extras.extend(opt.auto_requires(parsed[opt.name]))
    return extras


__all__ = [
    "OptionMode",
    "OptionSpec",
    "compute_auto_requires",
    "is_spec_with_options",
    "parse_options",
]
