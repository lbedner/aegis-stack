"""The Voice step's search, as the page's other big lists search (the model
catalog): the voices narrowed by provider, gender, tone and accent, and by
text, the first ``LIMIT`` of them listed and how many matched; and each
filter's options, as its checklist offers them. Accents come grouped by
language, the way Logs groups a page's containers: a language ticked takes
every accent of it.

Opened (no filter sent yet), the search is for voices like the chosen
one: its provider and accent (its gender and tone too would often leave
none).
"""

from typing import Any

from .overview import Frozen
from .traits import TONE_FAMILIES

# Each filter by the name it rides in the query as, and the voice's field.
FILTERS = {
    "provider": "provider",
    "gender": "gender",
    "family": "family",
    "language": "language",
    "accent_of": "accent",
}
# A filter sent: the form says so, so a filter cleared stays cleared (an
# unticked checklist sends nothing).
SENT = "filtered"
LIMIT = 50


class VoiceChoice(Frozen):
    """A voice as the designer offers it: who it sounds like (``detail``,
    as a line), its tone family and its accent's language."""

    id: str
    name: str
    provider: str
    provider_name: str
    gender: str
    tone: str
    family: str | None
    accent: str | None = None
    language: str | None = None
    detail: str
    description: str = ""


class FilterOption(Frozen):
    """One option of a filter's checklist (an accent indented under its
    language)."""

    name: str
    value: str
    label: str
    checked: bool
    indent: bool = False


class Finding(Frozen):
    """The search as drawn: its text, what each filter holds, each filter's
    options, the voices it keeps (the first ``LIMIT``, the chosen one left
    out: it is pinned above them) and how many matched."""

    q: str
    filters: dict[str, list[str]]
    options: dict[str, list[FilterOption]]
    cards: list[VoiceChoice]
    matched: int
    limit: int = LIMIT


def _asked(query: Any) -> dict[str, list[str]] | None:
    """What each filter holds in ``query`` (a request's query, or a plain
    mapping); None when none was sent."""
    if not query or SENT not in query:
        return None

    def values(name: str) -> list[str]:
        if hasattr(query, "getlist"):
            return [v for v in query.getlist(name) if v]
        found = query.get(name) or []
        return [found] if isinstance(found, str) else list(found)

    return {name: values(name) for name in FILTERS}


# What the search opens on: the chosen voice's own of these.
OPENED_ON = ("provider", "accent_of")


def _picked(query: Any, chosen: VoiceChoice | None) -> dict[str, list[str]]:
    """The filters: the query's, else (opened) the chosen voice's provider
    and accent."""
    asked = _asked(query)
    if asked is not None:
        return asked
    own = {name: getattr(chosen, FILTERS[name], None) for name in OPENED_ON}
    return {name: [own[name]] if own.get(name) else [] for name in FILTERS}


def _fits(
    v: VoiceChoice, filters: dict[str, list[str]], q: str, skip: str = ""
) -> bool:
    """Whether ``v`` is kept by every filter but ``skip``, and by ``q``."""
    for name in ("provider", "gender", "family"):
        if name != skip and filters[name] and getattr(v, name) not in filters[name]:
            return False
    accents, languages = filters["accent_of"], filters["language"]
    if skip != "accent" and (accents or languages):
        if v.accent not in accents and v.language not in languages:
            return False
    text = f"{v.name} {v.detail} {v.description}".lower()
    return not q or q.lower() in text


def _option(
    name: str, value: str, label: str, filters: dict[str, list[str]], **more: Any
) -> FilterOption:
    return FilterOption(
        name=name, value=value, label=label, checked=value in filters[name], **more
    )


def _accents(
    voices: list[VoiceChoice], filters: dict[str, list[str]]
) -> list[FilterOption]:
    """The accents of the voices the provider filter keeps, each language
    first (English leads) and its accents indented under it."""
    spoken: dict[str, set[str]] = {}
    for v in voices:
        if v.accent and v.language and _fits(v, filters, "", skip="accent"):
            spoken.setdefault(v.language, set()).add(v.accent)
    options: list[FilterOption] = []
    for language in sorted(spoken, key=lambda lang: (lang != "English", lang)):
        options.append(_option("language", language, language, filters))
        options += [
            _option("accent_of", accent, accent, filters, indent=True)
            for accent in sorted(spoken[language])
        ]
    return options


def find(voices: list[VoiceChoice], chosen: VoiceChoice | None, query: Any) -> Finding:
    """The search ``query`` asks for (opened: the chosen voice's filters)."""
    filters = _picked(query, chosen)
    q = str((query or {}).get("q") or "").strip()
    providers = {v.provider: v.provider_name for v in voices}
    genders = sorted({v.gender for v in voices})
    options = {
        "provider": [_option("provider", p, n, filters) for p, n in providers.items()],
        "gender": [_option("gender", g, g.title(), filters) for g in genders],
        "family": [
            _option("family", key, label, filters)
            for key, (label, _) in TONE_FAMILIES.items()
        ],
        "accent": _accents(voices, filters),
    }
    mine = chosen.id if chosen else None
    kept = [v for v in voices if v.id != mine and _fits(v, filters, q)]
    return Finding(
        q=q, filters=filters, options=options, cards=kept[:LIMIT], matched=len(kept)
    )
