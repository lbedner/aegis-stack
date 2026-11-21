"""What the assistant is cued to say on a live call (``chat_live``): how
it opens, into the quiet, about a picture shown, and at the time limit.
Cues, not scripts, so the words vary; the server's own, so the page never
puts words in its mouth."""

from typing import Any

from app.services.ai.service import realtime_calls

# Sent the moment the call is up, so the assistant speaks first: a cue
# rather than a line, so the greeting varies.
GREETING = (
    "The call just connected. Greet them warmly in a few words and ask "
    "what they would like to talk about."
)
# A call into a conversation already under way: no introductions.
CONTINUING = (
    "The call just connected, in a conversation you are already having with "
    "them (it is above). Greet them briefly as someone you know - no "
    "introductions - and ask what is next."
)
# A call soon after one dropped mid-answer picks it up.
RESUMING = (
    "The call just reconnected. It dropped while you were answering them; "
    'they had asked: "{asked}". Say in a few words that you got cut off, '
    "then pick that answer up."
)

# Into the quiet: no provider ends a call on silence, so the page counts it
# (call-state.js) and names one of these; the assistant says it. Cues, not
# scripts, so the words vary. The check-in is a question they can tell
# apart: "I'm ready when you are" went unnoticed as one.
CHECK_IN = (
    'It has gone quiet on the call. Ask them "Are you still there?" and nothing else.'
)
GOODBYE = (
    "It is still quiet; they seem to have stepped away. Say a short goodbye "
    "and end the call."
)
CUES = {"check_in": CHECK_IN, "goodbye": GOODBYE}

# A picture shown mid-call: what the turn is asked with it (nothing was
# said, the picture is the question), and the cue the assistant says what
# it saw from, in its own voice. A look that failed is said too: the page
# waits on it.
SHOWN = "(showing you this on the call)"
SAW = (
    "They just showed you a picture on the call and you looked at it. Tell "
    'them what you saw, in your own words: "{seen}"'
)
NOT_SEEN = (
    "They just showed you a picture on the call, but you could not look at "
    "it. Say so in a sentence and ask them to try again."
)
# What of the look is spoken: a few sentences, not the whole transcription.
SEEN_CHARS = 1_000

# Said this long before a mount's longest call (``chat_live.WRAP_UP_SECONDS``),
# and at it, to the page.
WRAP_UP = (
    "The call is nearly out of time. Tell them so in a sentence and say a "
    "short goodbye."
)
TIME_UP = "The call reached its time limit. You can carry on by typing."


def opening(conversation: Any) -> str:
    """How the call opens: picking up a dropped one, carrying on a
    conversation, or a first greeting."""
    if conversation is None:
        return GREETING
    if asked := realtime_calls.resumed(conversation):
        return RESUMING.format(asked=asked)
    return CONTINUING if conversation.messages else GREETING
