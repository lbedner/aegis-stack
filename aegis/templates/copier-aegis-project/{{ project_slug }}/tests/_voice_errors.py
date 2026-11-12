"""A voice provider's failure, for tests."""


class AnsweredError(Exception):
    """A provider SDK's error: the HTTP status it answered with on
    ``status_code``, and its own text, which can carry a key or a URL."""

    def __init__(
        self, status_code: int, text: str = "key=sk-secret at https://internal"
    ) -> None:
        super().__init__(text)
        self.status_code = status_code
