"""Domain errors mapped to HTTP status codes by the API layer."""

from __future__ import annotations

from typing import Any


class MindMapError(Exception):
    """Base class for errors that are safe to expose to API clients."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "error",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize the error for API responses / job records."""
        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
            "details": self.details,
        }


class UnsupportedMediaTypeError(MindMapError):
    """The upload is not a PDF (extension or MIME type)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="unsupported_media_type", status_code=415)


class FileTooLargeError(MindMapError):
    """The upload exceeds the configured size limit."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="file_too_large", status_code=413)


class InvalidPDFError(MindMapError):
    """The upload is corrupt, encrypted, or cannot be parsed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_pdf",
        details: dict | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=422, details=details)


class PageLimitError(MindMapError):
    """The document has more pages than configured."""

    def __init__(self, pages: int, limit: int) -> None:
        super().__init__(
            f"PDF has {pages} pages, exceeding the configured limit of {limit}.",
            code="page_limit_exceeded",
            status_code=422,
            details={"pages": pages, "limit": limit},
        )


class NoExtractableTextError(MindMapError):
    """The document is likely scanned or otherwise has no text layer."""

    def __init__(self) -> None:
        super().__init__(
            "No extractable text was found in this PDF. Scanned/image-only PDFs need OCR, "
            "which is not supported yet.",
            code="no_extractable_text",
            status_code=422,
        )


class LLMError(MindMapError):
    """The configured LLM failed or returned unusable output."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message, code="llm_error", status_code=502, details=details)


class GenerationError(MindMapError):
    """The pipeline could not produce a valid mind map."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message, code="generation_failed", status_code=502, details=details)


class JobNotFoundError(MindMapError):
    """Unknown or expired job id."""

    def __init__(self, job_id: str) -> None:
        super().__init__(
            f"Job '{job_id}' was not found (it may have expired).",
            code="job_not_found",
            status_code=404,
        )


class JobNotReadyError(MindMapError):
    """Result requested before the job completed."""

    def __init__(self, status: str) -> None:
        super().__init__(
            f"Job is not completed yet (current status: {status}).",
            code="job_not_ready",
            status_code=409,
        )
