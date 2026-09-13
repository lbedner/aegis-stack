"""Every field ``SyncResult`` collects must reach the operator.

``answers_backfilled`` was populated from the day it was written and read
nowhere outside ``template_cleanup`` — so ``aegis update`` answered questions
the project had never been asked (``ollama_mode`` defaulting to ``none``) and
said nothing, and the consequence surfaced as an ImportError at boot
(aegis-stack#1120). A field worth collecting is worth printing; this is the
ratchet that says so for the next one.
"""

from dataclasses import fields
from pathlib import Path

from aegis.core.template_cleanup import SyncResult

UPDATE_COMMAND = Path(__file__).parents[2] / "aegis" / "commands" / "update.py"


def test_every_collected_field_is_reported() -> None:
    source = UPDATE_COMMAND.read_text()
    unreported = [
        f.name for f in fields(SyncResult) if f"sync_result.{f.name}" not in source
    ]
    assert not unreported, (
        f"SyncResult collects these and aegis update never shows them: {unreported}"
    )
