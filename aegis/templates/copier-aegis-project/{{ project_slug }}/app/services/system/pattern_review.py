"""``patterns review``: Illiana's write-up of a change's new findings
(``pattern_check.new_spots``) and what it touches, for a pull request.

The facts are the findings: every one is listed from the check, with its
place, rule and what to do, and her words sit beside each. What she sees
past them is set apart as opinion, so she can neither invent a finding nor
drop one. One call, as its agent row writes (``writer``, ``REVIEWER``):
no tools; none when nothing is new (her seal of approval, ``SEAL``,
instead), or when the findings are the ones an earlier review
(``fingerprint``) already covered. One comment tells the
whole sequence: the latest review on top, each earlier one below it."""

import json
import re

from pydantic import BaseModel

from app.core.figures import FIGURES
from app.core.log import logger
from app.services.system.errors.fingerprint import digest
from app.services.system.pattern_check import Spot, breaks

# The comment's first line, how CI finds it again to edit; its second,
# which findings it covered.
MARKER = "<!-- illiana-review -->"
# A change with nothing new: her seal of approval, posted like any review.
SEAL = "Nothing new against any rule I hold. This has my seal of approval."
# What stands for her write-up when the model does not answer: the verdict
# and every place are the rules', so a change is reviewed either way.
UNSAID = (
    "My write-up did not come through this time, so each rule speaks for "
    "itself below. The verdict stands either way."
)
# Below the latest review, the ones before it.
EARLIER = "#### Earlier reviews"
# GitHub refuses a comment past 65,536 characters: the oldest go first.
MOST_CHARS = 60_000
ACTION = "patterns_review"
# The most she reads and the comment lists: a first run with no baseline
# brings every finding the app has.
MOST_LISTED = 50
# Places of one rule listed as they are; past this, folded under a count.
SHOWN = 3
TOUCHES = "What this change touches"
OPINION = "#### Beyond the findings (my opinion)"
# Its agent: an ``agent`` row the AI service seeds (her persona and the
# reviewing below), so its model and how long it writes are set in Agents.
REVIEWER = "pr-reviewer"
REVIEWING = """## Reviewing a pull request

When I review a change for its pull request, the facts are its new findings,
from the app's own pattern rules (each rule's why and what to do, once), and
what it touches; nothing else about the change is known to me. I write to
the person who made the change, as myself: "I", "you", plain sentences.

- ``summary``: two to four sentences on what the findings mean together.
  The verdict is the rules', said above my words: a finding that ``blocks``
  holds the change, and then I say why it holds and what clears it, never
  that it could merge as it is. The findings, their places and what the
  change touches are shown under my words, so I never list them or count
  them again.
- ``notes``: one per rule that fired, by its ``check``: what it means in
  this change and what to do, in a sentence or two, without repeating the
  rule's own why.
- ``opinion``: anything I would point out beyond the findings, never as a
  finding.

I do not invent findings, and I do not call one fine when the rules flag it.
"""


def reviewer_prompt(persona: str) -> str:
    """The reviewer's prompt: Illiana's ``persona``, then the reviewing."""
    return f"{persona.rstrip()}\n\n{REVIEWING}"


class Note(BaseModel):
    """What she says of one rule's findings, by its ``check``."""

    model_config = FIGURES

    check: str
    said: str


class Review(BaseModel):
    model_config = FIGURES

    summary: str
    notes: tuple[Note, ...] = ()
    opinion: str = ""


def fingerprint(fresh: list[Spot], touched: str) -> str:
    """Which findings (and touches) a review covers: the same, no new one."""
    return digest([*sorted(s.key for s in fresh), touched])[:16]


def facts(fresh: list[Spot], touched: str) -> str:
    """What she is told, compact: each rule once, each finding by its place,
    rule and part, and what the change touches."""
    rules = {
        s.finding.check: s.finding.model_dump(include={"title", "why", "action"})
        | {"blocks": s.finding.blocking}
        for s in fresh
    }
    found = [
        {"place": s.at, "check": s.finding.check, "part": s.finding.subject}
        for s in fresh
    ]
    body = {"rules": rules, "new_findings": found, "touches": touched}
    return json.dumps(body, separators=(",", ":"))


def markdown(fresh: list[Spot], said: Review, touched: str, commit: str = "") -> str:
    """A review: her words, then each rule that fired once (her note on it,
    else its why) with its places, her opinion set apart, and what the
    change touches folded away; headed by the commit it reviewed."""
    notes = {n.check: n.said for n in said.notes}
    title = (
        f"### Illiana's review of `{commit[:7]}`" if commit else "### Illiana's review"
    )
    head = [MARKER, f"<!-- spots:{fingerprint(fresh, touched)} -->", title]
    parts = [*head, "", _verdict(fresh), "", said.summary, ""]
    for check, spots in _by_rule(fresh).items():
        found = spots[0].finding
        weight = "blocks" if found.blocking else "advisory"
        parts += [
            f"**{found.title}** · `{check}` · {weight}",
            "",
            notes.get(check) or found.why,
            "",
            _places(spots),
            "",
        ]
    if said.opinion:
        parts += [OPINION, "", said.opinion, ""]
    if touched:
        parts += [_folded(touched), ""]
    return "\n".join(parts)


def _verdict(fresh: list[Spot]) -> str:
    """Blocked or clear, the rules' (``Finding.blocking``), never hers."""
    blocked = sum(s.finding.blocking for s in fresh)
    if blocked:
        return f"**Blocked.** {breaks(blocked)} a rule that holds a change."
    return "**Clear.** Nothing new here holds the change."


def _by_rule(fresh: list[Spot]) -> dict[str, list[Spot]]:
    """The findings by the rule that fired, in the order each first came."""
    found: dict[str, list[Spot]] = {}
    for spot in fresh:
        found.setdefault(spot.finding.check, []).append(spot)
    return found


def _places(spots: list[Spot]) -> str:
    """A rule's places, folded under their count past ``SHOWN``."""
    listed = "\n".join(f"- `{s.at}`" for s in spots)
    if len(spots) <= SHOWN:
        return listed
    return f"<details><summary>{len(spots)} places</summary>\n\n{listed}\n\n</details>"


def _folded(touched: str) -> str:
    """What the change touches (``touches.summary``) under its own heading,
    closed."""
    lines = touched.strip().splitlines()
    heading = TOUCHES
    if lines and lines[0].startswith("#"):
        heading = lines[0].lstrip("# ").strip()
        lines = lines[1:]
    body = "\n".join(lines).strip()
    return f"<details><summary>{heading}</summary>\n\n{body}\n\n</details>"


async def review(
    fresh: list[Spot], touched: str, previous: str = "", commit: str = ""
) -> str:
    """The comment for ``fresh`` at ``commit``, above the reviews before it
    (``previous``, the comment as it stands); nothing at all when those
    reviews already covered these findings, and no call when nothing is
    new."""
    if previous and _covered(previous) == fingerprint(fresh, touched):
        return ""
    if not fresh:
        now = markdown([], Review(summary=SEAL), touched, commit)
    else:
        shown = fresh[:MOST_LISTED]
        try:
            said = await _ask(facts(shown, touched))
        except Exception:
            logger.exception("Illiana's review write-up failed; the rules speak")
            said = Review(summary=UNSAID)
        now = markdown(shown, said, touched, commit)
        if more := len(fresh) - len(shown):
            now += f"\n_... and {more} more; `patterns check` lists them all._\n"
    return _with_earlier(now, previous)


def _covered(previous: str) -> str:
    """The findings a comment's latest review covered (its fingerprint)."""
    found = re.search(r"<!-- spots:([0-9a-f]+) -->", previous)
    return found.group(1) if found else ""


def _with_earlier(now: str, previous: str) -> str:
    """``now`` on top, then every earlier review, newest first, each
    collapsed under its heading as it was written; the oldest dropped
    where the comment would pass GitHub's limit."""
    if not previous:
        return now
    was, _, earlier = previous.partition(EARLIER)
    lines = [line for line in was.strip().splitlines() if not line.startswith("<!--")]
    title = lines[0].removeprefix("### ") if lines else "Illiana's review"
    body = "\n".join(lines[1:]).strip()
    blocks = [
        f"<details><summary>{title}</summary>\n\n{body}\n\n</details>",
        *re.findall(r"<details>.*?</details>", earlier, re.DOTALL),
    ]
    while len(blocks) > 1 and len(now) + sum(map(len, blocks)) > MOST_CHARS:
        blocks.pop()
    return "\n".join([now.rstrip(), "", EARLIER, "", *blocks, ""])


async def _ask(facts_text: str) -> Review:
    """Its answer, written as its agent row writes (her persona and the
    reviewing while the row is missing), its spend recorded."""
    from app.services.ai.service import DEFAULT_SYSTEM_PROMPT, write

    review, _ = await write(
        REVIEWER,
        reviewer_prompt(DEFAULT_SYSTEM_PROMPT),
        Review,
        f"The change's findings:\n{facts_text}",
        action=ACTION,
        owner_user_id=None,
    )
    return review
