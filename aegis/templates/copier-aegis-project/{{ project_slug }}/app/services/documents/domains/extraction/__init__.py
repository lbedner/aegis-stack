"""Reading a document, one page at a time.

- ``pages`` - the run itself: which pages need reading, and what each becomes
- ``pdf`` - pypdfium2: a page's text layer, and the page rendered to PNG
- ``vision`` - the reader a page without a text layer is handed to
- ``dispatch`` - where a run happens: the worker's queue, or here
- ``jobs`` - the entry points a run is started through, in either place
"""

from app.services.documents.domains.extraction.pages import (
    ExtractionResult,
    VisionReader,
    extract_document,
)

__all__ = ["ExtractionResult", "VisionReader", "extract_document"]
