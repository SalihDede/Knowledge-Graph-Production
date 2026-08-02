from __future__ import annotations


class IngestionError(Exception):
    """Raised when a PDF/URL document cannot be turned into text+segments.

    `retryable` tells the worker whether to retry (transient network/OCR
    failures) or fail immediately (bad input: corrupt file, blocked URL,
    oversized content -- retrying would just fail the same way again).
    """

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
