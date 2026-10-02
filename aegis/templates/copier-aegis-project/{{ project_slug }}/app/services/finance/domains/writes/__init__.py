"""Finance's change types for the propose/approve queue (FW-05).

The queue itself lives in ``app.services.change_queue``; finance is one
of its registrants. Importing this package registers finance's types -
an executor that is never imported does not exist to the queue.
"""

from app.services.finance.domains.writes import executors as executors
