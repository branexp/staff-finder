"""Shared error taxonomy for batch tasks."""

from __future__ import annotations

from enum import StrEnum


class BatchTaskError(Exception):
    """Base exception for batch task errors."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or "UNKNOWN_ERROR"


class ValidationError(BatchTaskError):
    """Input validation failed."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="VALIDATION_ERROR")


class TransientError(BatchTaskError):
    """Transient error that may be retried (429, 5xx, timeout)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="TRANSIENT_ERROR")


class NotFoundError(BatchTaskError):
    """Resource not found (no search results, missing data)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="NOT_FOUND")


class ProcessingError(BatchTaskError):
    """Non-recoverable processing error."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="PROCESSING_ERROR")


class ErrorCode(StrEnum):
    """Standardized error codes for batch task results."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    NOT_FOUND = "NOT_FOUND"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    SUCCESS = "SUCCESS"


def is_transient_http_error(exc: BaseException) -> bool:
    """Return True for transient HTTP errors (429, 5xx, timeouts)."""
    try:
        import httpx

        if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            return exc.response.status_code == 429 or (500 <= exc.response.status_code < 600)
    except ImportError:
        pass
    return False
