"""Runs changing (asked, taken, finished) in this process, to whoever
watches here (``watching``: the bot in a call), at once instead of on its
next look. A task started inside (a run made in the app) carries it. A run
another process changes is not heard here: the bot reads it on its beat."""

from app.core.hooks import Hook

_runs = Hook("runs")
watching = _runs.watching


def changed() -> None:
    """A run changed, to whoever is watching."""
    _runs.tell()
