"""Mail read the way documents read paper.

It arrives two ways and is read one way: a mailbox export (``.mbox``) or
a saved message (``.eml``) uploaded like any other document, or a pull
over IMAP with an app password (``pull``: read-only, no OAuth). Either
way each message is kept once, by its Message-ID, its body filed as a
letter and each attachment as a document of its own.

- ``parse`` - bytes to messages, pure stdlib
- ``ingest`` - messages to rows and documents, in short holds
- ``jobs`` - a dropped file's import as a job, on the worker where there is one
- ``pull`` - the mailbox the secrets name, every half hour (``scheduled_jobs``)
- ``arrivals`` - what came in and what each message became, for the page
  and the ``arrivals`` tool

Who a sender IS is not this service's question: ingest hands each batch's
new messages to whatever registered with ``register_messages_filed`` (a
contacts service matching ``from_address``). The template registers
nothing there.

Distinct from ``comms``, which SENDS.
"""

from app.core.constants import ServiceName

# Part of documents: mail read into documents (``ownership``).
PART_OF = ServiceName.DOCUMENTS
