"""Constants for modal layouts and dimensions."""


class ModalLayout:
    """Modal layout constants."""

    DEFAULT_WIDTH = 1100
    DEFAULT_HEIGHT = 700
    SECTION_DIVIDER_HEIGHT = 20
    # Spent INSIDE the declared modal width, so content sized to fill a
    # modal has this much less room than the width suggests.
    CONTENT_PADDING = 20


class ModalSections:
    """Section layout constants."""

    STAT_LABEL_WIDTH = 150
    METRIC_CARD_ICON_SIZE = 32


class TableColumns:
    """Table column widths for consistency across modals."""

    # Worker modal columns
    WORKER_STATUS_ICON = 30
    WORKER_QUEUED = 80
    WORKER_PROCESSING = 80
    WORKER_COMPLETED = 100
    WORKER_FAILED = 80
    WORKER_SUCCESS_RATE = 100
    WORKER_STATUS = 80

    # Backend modal columns
    BACKEND_PATH = 300
    BACKEND_METHODS = 150
    BACKEND_TAGS = 150
    BACKEND_NAME = 200
