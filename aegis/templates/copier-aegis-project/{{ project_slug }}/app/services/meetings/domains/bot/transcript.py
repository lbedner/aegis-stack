"""The call's captions as transcript lines (``Transcript``): when what was
said is written, and when a line put to the bot is taken as said in full."""

import asyncio
from collections.abc import Callable
from difflib import SequenceMatcher
import re

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.log import logger
from app.services.meetings.domains.bot.meet import merge_caption
from app.services.meetings.domains.bot.row import write_captions
from app.services.meetings.domains.moments.detectors import (
    FOLLOW_SECONDS,
    ITSELF,
    Before,
    cut_at_name,
    its_own,
    mentions,
    replying,
    stops,
)
from app.services.meetings.models import Caption

# How often the run beats and reads back its status: a leave request waits
# at most this long, and on SQLite each beat takes the write lock.
BEAT_SECONDS = 10.0
# How long a line for the bot stops changing before it is taken as said:
# captions put a question mark on every pause.
# ponytail: a fixed pause; tune it from real calls.
SETTLE_SECONDS = 2.0
# Meet at times starts a second block for what a speaker is still saying
# (its words captioned anew): one opening like theirs from this recently,
# this alike over its first characters, is that line drawn again.
# A block begun with fewer letters than ``FEWEST_LETTERS`` is waited on
# (within ``AGAIN_SECONDS``) until there is enough of it to tell.
AGAIN_SECONDS = 3.0
ALIKE = 0.75
OPENING = 40
FEWEST_LETTERS = 8


def _letters(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


def said_again(before: str, shown: str) -> bool:
    """Whether ``shown`` opens with words ``before`` already said (letters
    only, over the first ``OPENING``, to ``ALIKE``): opening alike (the name
    spelled anew), or found whole in it, from mid-way (Meet draws a block
    again from its start or from mid-way)."""
    a, b = _letters(before), _letters(shown)
    n = min(len(a), len(b), OPENING)
    if n < FEWEST_LETTERS:
        return False
    if SequenceMatcher(None, a[:n], b[:n]).ratio() >= ALIKE:
        return True
    found = SequenceMatcher(None, a, b[:n], autojunk=False).find_longest_match()
    return found.size >= ALIKE * n


class Transcript:
    """The call's captions as transcript lines, timed from when the bot got
    in. What changed is due every ``BEAT_SECONDS`` (each write takes
    SQLite's write lock; ``take``), and what is left on the way out
    (``rest``), each written on the caller's session (``write``). A
    line for the bot (``bot``: naming it, or said back to it right after it
    spoke by the one it answered, ``asker``) is
    held until it stops changing for ``SETTLE_SECONDS``, then due at once:
    a question put to it is never taken half said, nor waits on a beat. A
    caption is cut into a line for each time it names the bot
    (``cut_at_name``), so each question put to it is its own. Each write
    gives back the moments it made. When the bot is talking, and what it
    says, is its own to tell (``her``: ``Answers.talk``): Meet captions it
    late, or not at all."""

    def __init__(self, meeting_id: int, bot: str) -> None:
        self.meeting_id, self.bot = meeting_id, bot
        self.started = self.written_at = asyncio.get_running_loop().time()
        self.rows: dict[str, int] = {}  # caption line (its piece) -> row
        self.lines: dict[str, str] = {}  # caption line (its piece) -> its text
        self.changed: dict[str, float] = {}  # ... -> when it last changed
        # piece -> the line before it, as the detectors read it (``Before``)
        self.before: dict[str, Before] = {}
        # piece -> what its ``before`` was told of her, and her words since
        self.her_heard: dict[str, tuple[str, str]] = {}
        self.bot_spoke = -FOLLOW_SECONDS - 1  # when its own caption last moved
        self.bot_said = ""  # what that caption says
        # When what the bot says has played, and what it last said.
        self.her: Callable[[], tuple[float, str]] = lambda: (float("-inf"), "")
        self.asker = ""  # who last put something to it
        self.asked: dict[str, str] = {}  # speaker -> their last line for it
        self.held: set[str] = set()  # pieces for it, not yet said in full
        self.seen: dict[str, str] = {}  # caption line -> its text, last look
        self.text: dict[str, str] = {}  # caption line -> all of it heard so far
        # caption line -> when it was first captioned, from when the bot got in
        self.first_seen: dict[str, float] = {}
        self.pending: dict[str, Caption] = {}
        # When each speaker's caption last moved: who was talking when.
        self.spoke: list[tuple[float, str]] = []
        # speaker -> their last block moved: Meet's, its line, and when
        self.latest: dict[str, tuple[str, str, float]] = {}
        self.drawn_as: dict[str, str] = {}  # Meet's block -> the line it redraws
        self.drawn_over: set[str] = set()  # blocks drawn again by another
        self.unsure: dict[str, Caption] = {}  # blocks too short yet to tell

    def take(self, captions: list[Caption]) -> list[Caption]:
        """What is due to be written, of ``captions`` and those held."""
        now = asyncio.get_running_loop().time()
        # Those waited on are looked at again, shown now or not (what Meet
        # shows now over what it showed then).
        for shown in {**self.unsure, **{c.line: c for c in captions}}.values():
            self._look(shown, now, patient=True)
        self._hear_her()
        # A stop is due at once: it waits on neither a pause nor the beat.
        stopping = {line for line, c in self.pending.items() if self._stops(c)}
        held = self.held = {
            line
            for line, c in self.pending.items()
            if line not in stopping
            and self._for_bot(c)
            and now - self.changed[line] < SETTLE_SECONDS
        }
        settled = bool(stopping) or any(
            self._for_bot(c) for line, c in self.pending.items() if line not in held
        )
        if settled or now - self.written_at >= BEAT_SECONDS:
            return self._due(held)
        return []

    def _hear_her(self) -> None:
        """What she has said so far, to each line not yet written: her
        caption and its echo under the asker's name grow together (taken in
        either order), so an echo is told by all she said while it grew,
        not by what she had said when it began."""
        _, words = self.her()
        heard = f"{self.bot_said} {words}"
        for line in self.pending:
            before = self.before.get(line)
            if before is None:
                continue
            # What it was told before, and her words then: words that grow
            # replace their last telling, others follow it.
            base, last = self.her_heard.get(line, (before[3], ""))
            if not heard.startswith(last):
                base = f"{base} {last}"
            self.her_heard[line] = (base, heard)
            self.before[line] = (*before[:3], f"{base} {heard}")

    def hearing(self) -> list[tuple[str, str]]:
        """The lines for the bot still being said (``held``), first begun
        first: who is saying each, and what of it so far."""
        return [
            (self.pending[line].speaker, self.pending[line].text)
            for line in sorted(self.held, key=lambda line: self.first_seen[line])
        ]

    def rest(self) -> list[Caption]:
        """Everything not yet written, held or not: on the way out."""
        now = asyncio.get_running_loop().time()
        for shown in list(self.unsure.values()):
            self._look(shown, now, patient=False)
        return self._due(set())

    def _look(self, shown: Caption, now: float, patient: bool) -> None:
        """One block Meet shows, taken in: under its own line, or the one it
        draws again; one too short yet to tell waits (``patient``)."""
        if shown.line in self.drawn_over or self.seen.get(shown.line) == shown.text:
            return
        if patient and self._too_soon(shown, now):
            self.unsure[shown.line] = shown
            return
        self.unsure.pop(shown.line, None)
        line = (
            self.drawn_as.get(shown.line) or self._drawn_again(shown, now) or shown.line
        )
        c = Caption(line, shown.speaker, shown.text)
        self.seen[shown.line] = c.text
        self.text[line] = merge_caption(self.text.get(line, ""), c.text)
        if its_own(c.speaker, self.bot):
            self.bot_spoke, self.bot_said = now, self.text[line]
        self.spoke.append((now, c.speaker))
        self.latest[c.speaker] = (shown.line, line, now)
        self._cut(c, now)

    def _too_soon(self, shown: Caption, now: float) -> bool:
        """Whether a block Meet has just begun is still too short to tell
        from its speaker's last (``said_again``): it is looked at again."""
        last = self.latest.get(shown.speaker)
        return (
            shown.line not in self.seen
            and last is not None
            and now - last[2] <= AGAIN_SECONDS
            and len(_letters(shown.text)) < FEWEST_LETTERS
        )

    def _drawn_again(self, shown: Caption, now: float) -> str | None:
        """The line a block Meet has just begun draws again (``said_again``
        its speaker's last, moved within ``AGAIN_SECONDS``), its old block
        then let go; None for a block of its own."""
        last = self.latest.get(shown.speaker)
        if shown.line in self.seen or last is None:
            return None
        block, line, moved = last
        if now - moved > AGAIN_SECONDS or not said_again(self.text[line], shown.text):
            return None
        self.drawn_as[shown.line] = line
        self.drawn_over.add(block)
        self.text[line] = ""  # the new block holds the line whole
        return line

    def _for_bot(self, caption: Caption) -> bool:
        """Whether a piece is put to the bot: someone else's, naming it or
        begun right after it spoke."""
        if its_own(caption.speaker, self.bot):
            return False
        return self._back(caption) or mentions(caption.text, self.bot)

    def _stops(self, caption: Caption) -> bool:
        """Whether a piece someone else said is a stop (``stops``): whether
        they may stop the bot is the detector's to say, once written."""
        return not its_own(caption.speaker, self.bot) and stops(caption.text, self.bot)

    def _back(self, caption: Caption) -> bool:
        """Whether a piece is said back to the bot (``replying``: the rule
        the detectors read it by)."""
        return replying(
            self.before.get(caption.line), caption.speaker, self.bot, caption.text
        )

    def _cut(self, caption: Caption, now: float) -> None:
        """The caption's pieces (``cut_at_name``) that changed, to write:
        the first under its own line, each after it as one of its own."""
        pieces = cut_at_name(self.text[caption.line], self.bot)
        for i, piece in enumerate(pieces):
            line = caption.line if i == 0 else f"{caption.line}#{i}"
            if self.lines.get(line) != piece:
                if line not in self.lines:
                    played, words = self.her()
                    gap = now - max(self.bot_spoke, played)  # < 0: it is talking
                    said = f"{self.bot_said} {words}"
                    self.before[line] = (ITSELF, gap, self.asker, said)
                self.lines[line] = piece
                self.changed[line] = now
                self.first_seen.setdefault(line, now - self.started)
                self.pending[line] = Caption(line, caption.speaker, piece)

    def _due(self, held: set[str]) -> list[Caption]:
        """What changed, but the pieces ``held``: taken as written now."""
        self.written_at = asyncio.get_running_loop().time()
        writing = [c for line, c in self.pending.items() if line not in held]
        self.pending = {line: self.pending[line] for line in held}
        for c in writing:
            if self._stops(c):  # nobody is answered now: only her name wakes her
                self.asker = ""
                continue
            if not self._for_bot(c):
                continue
            if (first := self._asked_again(c)) is not None:
                # Written over the line it says again: one question, asked once.
                self.rows[c.line] = self.rows[first]
                logger.info(
                    "Bot: a line for it drawn twice, kept as one",
                    meeting_id=self.meeting_id,
                    speaker=c.speaker,
                    first=self.lines[first],
                    again=c.text,
                    blocks=(first, c.line),
                )
                continue
            self.asker, self.asked[c.speaker] = c.speaker, c.line
            logger.info(
                "Bot: a line for it, said in full",
                meeting_id=self.meeting_id,
                speaker=c.speaker,
                text=c.text,
                said_back=self._back(c),
                quiet_seconds=round(self.written_at - self.changed[c.line], 1),
            )
        return writing

    def _asked_again(self, caption: Caption) -> str | None:
        """The line for the bot ``caption`` says again: its speaker's last,
        written already, begun within ``AGAIN_SECONDS`` of it and opening
        alike (``said_again``). Meet at times draws one question as two
        blocks in a way ``_drawn_again`` misses (the second with the name
        spelled anew). None for a line of its own."""
        first = self.asked.get(caption.speaker)
        if first is None or first not in self.rows or caption.line in self.rows:
            return None
        begun = abs(self.first_seen[caption.line] - self.first_seen[first])
        if begun > AGAIN_SECONDS or not said_again(self.lines[first], caption.text):
            return None
        return first

    async def write(
        self, db: AsyncSession, writing: list[Caption]
    ) -> list[tuple[int, str]]:
        """``writing`` (from ``take`` or ``rest``) as transcript lines, and
        the moments it made."""
        return await write_captions(
            db,
            self.meeting_id,
            writing,
            self.rows,
            self.written_at - self.started,
            starts=self.first_seen,
            before=self.before,
        )
