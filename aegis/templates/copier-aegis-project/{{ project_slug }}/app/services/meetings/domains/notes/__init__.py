"""A meeting's notes as kept: each item a row (``MeetingNoteItem``) citing
the transcript lines it came from (``MeetingNoteLine``), each name the
model gave pointing at the person it is. ``Notes`` is how they are written
and read; the rows are how they are kept.

- ``service`` - keep a meeting's notes (or why they failed), read them back
- ``queries`` - the reads and writes behind it
"""
