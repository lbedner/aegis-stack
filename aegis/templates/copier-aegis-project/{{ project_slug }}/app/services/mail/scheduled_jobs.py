"""The mail service's scheduled jobs (``app.core.schedule``)."""

from app.core.schedule import LONG_RUNNING, ServiceJob
from app.services.mail.pull import mail_pull_job

JOBS: tuple[ServiceJob, ...] = (
    # The mailbox the secrets name, every half hour; nothing until one is
    # set. Not server_only: a second reader of a read-only mailbox costs
    # nobody anything, and a dev stack with a mailbox set wants its mail.
    ServiceJob(
        mail_pull_job,
        "mail_pull",
        "Mail: Pull The Mailbox",
        {"trigger": "interval", "minutes": 30},
        timeout=LONG_RUNNING,
    ),
)
