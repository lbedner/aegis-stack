"""An answer as it should be said: the agent's words, without the markup.

The stack used to rewrite answers for speech with a second model call, run
as its own persisted conversation under ``system_voice_convert`` and outside
the agent that answered. That cost a model call per turn, wrote a history
nobody asked for, and could say something the agent had not. Markdown is
layout, not content, so it is stripped here instead.
"""

import re

_FENCED = re.compile(r"```.*?```", re.DOTALL)
# Link text holds no "[" and a target no "(": each attempt then stops at the
# next bracket rather than scanning to the end, which made a run of "["
# quadratic (CodeQL py/polynomial-redos).
_LINK = re.compile(r"!?\[([^\[\]]*)\]\([^()]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3}|~~|`)")
# One class for the prefix: two \s* around an optional "|" could both match
# the same spaces, which went quadratic on a long run of them.
_TABLE_RULE = re.compile(r"^[\s|:]*-{2,}")
_ENDS_A_SENTENCE = (".", "!", "?", ":", ";")


def to_spoken(text: str, max_chars: int = 4096) -> str:
    """Plain sentences from markdown, cut at a sentence end within ``max_chars``."""
    text = _LINK.sub(r"\1", _FENCED.sub("", text))
    lines = []
    for raw in text.splitlines():
        if _TABLE_RULE.match(raw):
            continue
        line = _EMPHASIS.sub("", _BULLET.sub("", _HEADING.sub("", raw)))
        line = " ".join(line.replace("|", " ").split())
        if line:
            lines.append(line)
    spoken = " ".join(
        line
        if index == len(lines) - 1 or line.endswith(_ENDS_A_SENTENCE)
        else f"{line}."
        for index, line in enumerate(lines)
    )
    if len(spoken) <= max_chars:
        return spoken
    cut = spoken[:max_chars]
    end = max(cut.rfind(mark + " ") for mark in ".!?")
    return cut[: end + 1] if end > max_chars // 2 else cut.rstrip() + "..."
