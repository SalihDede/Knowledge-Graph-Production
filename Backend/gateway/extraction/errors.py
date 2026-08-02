from __future__ import annotations


class ExtractionError(Exception):
    """Raised when an extraction provider/adapter cannot produce triplets.

    `status_code` mirrors the HTTP status the synchronous `/api/extract`
    endpoint should surface. `retryable` tells the worker whether a transient
    retry is worth attempting (upstream/network failures) or whether the
    error is deterministic (bad input, unknown kg_type, missing credentials).
    """

    def __init__(self, message: str, *, status_code: int = 502, retryable: bool = True):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
