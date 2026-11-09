"""The honeypot every public form shares.

A form-filler bot fills every input it finds; a person never sees this one
(the web frontend's ``honeypot()`` macro in ``components/macros/form.html``
renders it out of sight and out of the tab order). A handler asks
``tripped`` with what was submitted and, when it was, answers with a real
submit's status and destination while doing nothing: no row, no email, no
session.

It lives with the backend's other request guards because the JSON API
checks it too, with or without the web frontend.
"""

from collections.abc import Mapping
from typing import Any

from app.core.log import logger

# A name a bot expects to fill. The macro reads it as ``honeypot_field``.
FIELD = "website"


def tripped(fields: Mapping[str, Any], *, form: str) -> bool:
    """Whether the submitted ``fields`` (a form or a JSON body) filled the
    trap; ``form`` names the form in the ``form.honeypot`` log event."""
    filled = bool(str(fields.get(FIELD) or "").strip())
    if filled:
        logger.warning("form.honeypot", form=form)
    return filled
