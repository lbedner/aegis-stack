"""Mail settings, kept out of config.py's size budget.

``Settings`` inherits these, so they load from ``.env`` like every other
setting. The IMAP four are read through ``secrets.get`` (``pull``): set
here they win, else the encrypted store's.
"""

from pydantic_settings import BaseSettings


class MailSettings(BaseSettings):
    # A mailbox export (.mbox, .eml) read into documents: its size at the
    # door, and how many messages one file files (the rest is skipped with
    # a warning, never a failed import).
    MAIL_IMPORT_MAX_BYTES: int = 100 * 1024 * 1024
    MAIL_IMPORT_MAX_MESSAGES: int = 2000
    # The mailbox the app pulls every half hour; nothing until host, address
    # and app password are set. The folder defaults to INBOX.
    MAIL_IMAP_HOST: str | None = None
    MAIL_IMAP_USER: str | None = None
    MAIL_IMAP_FOLDER: str | None = None
    MAIL_IMAP_PASSWORD: str | None = None
