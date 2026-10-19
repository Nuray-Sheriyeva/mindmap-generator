"""HTTP routes for upload, polling and export."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, File, Form, Response, UploadFile
from fastapi.responses import JSONResponse

from ..errors import (
    FileTooLargeError,
    InvalidPDFError,
    JobNotFoundError,
    JobNotReadyError,
    MindMapError,
    UnsupportedMediaTypeError,
)
from ..jobs.exports import export_json, export_markdown
from ..jobs.store import JobStatus
from ..models import GenerationOptions
from ..pdf.extract import inspect_pdf
from .deps import JobStoreDep, LLMDep, RunnerDep, SettingsDep
from .schemas import ErrorResponse, HealthResponse, JobResponse, UploadResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mindmaps"])

_PDF_MIME_TYPES = {"application/pdf", "application/x-pdf"}
_CHUNK_SIZE = 1024 * 1024
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})?$")


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Stream an upload into memory while enforcing the size limit."""
    buffer = bytearray()
    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise FileTooLargeError(
                f"File exceeds the maximum upload size of {max_bytes // (1024 * 1024)} MB."
            )
    if not buffer:
        raise InvalidPDFError("The uploaded file is empty.", code="empty_file")
    return bytes(buffer)


def _validate_filename_and_mime(file: UploadFile) -> str:
    filename = Path(file.filename or "").name
    if not filename or not filename.lower().endswith(".pdf"):
        raise UnsupportedMediaTypeError("Only files with the .pdf extension are accepted.")
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in _PDF_MIME_TYPES:
        raise UnsupportedMediaTypeError(
            f"Unsupported media type '{mime or 'unknown'}'. Upload a PDF "
            "(Content-Type: application/pdf)."
        )
    return filename


@router.get("/health", response_model=HealthResponse, summary="Health check")
async def health(settings: SettingsDep, llm: LLMDep) -> HealthResponse:
    """Liveness probe with non-secret provider configuration."""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        llm_provider=llm.provider,
        llm_model=llm.model,
        cache_enabled=settings.cache_enabled,
    )


@router.post(
    "/mindmaps",
    response_model=UploadResponse,
    status_code=202,
    responses={
        413: {"model": ErrorResponse, "description": "File too large"},
        415: {"model": ErrorResponse, "description": "Not a PDF"},
        422: {"model": ErrorResponse, "description": "Invalid, encrypted or oversized PDF"},
    },
    summary="Upload a PDF and start mind map generation",
)
async def create_mindmap(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="Text-based PDF document")],
    settings: SettingsDep,
    store: JobStoreDep,
    runner: RunnerDep,
    max_depth: Annotated[int | None, Form(description="Levels below the root (2-3)")] = None,
    max_branches: Annotated[int | None, Form(description="Main branches (2-12)")] = None,
    language: Annotated[
        str | None,
        Form(description="Output language ISO code; omit to mirror the document"),
    ] = None,
) -> UploadResponse:
    """Validate the upload, create a background job, and return its id."""
    filename = _validate_filename_and_mime(file)
    data = await _read_upload(file, settings.max_upload_bytes)
    await file.close()

    # Offload PyMuPDF's page-tree inspection so the event loop stays responsive.
    await asyncio.to_thread(inspect_pdf, data, settings)

    requested_language = (language or "").strip().lower()
    if requested_language in {"", "auto"}:
        requested_language = None
    elif not _LANGUAGE_PATTERN.fullmatch(requested_language):
        raise MindMapError(
            "language must be an ISO-639 code such as 'en', 'ru' or 'zh-CN'.",
            code="invalid_language",
            status_code=422,
        )

    options = GenerationOptions(
        max_depth=settings.clamp_max_depth(max_depth),
        max_branches=settings.clamp_max_branches(max_branches),
        max_children=settings.max_children,
        language=requested_language,
    )
    file_hash = hashlib.sha256(data).hexdigest()
    job = store.create(filename=filename, file_hash=file_hash)
    background_tasks.add_task(
        runner.run,
        job_id=job.job_id,
        pdf_bytes=data,
        filename=filename,
        file_hash=file_hash,
        options=options,
    )
    logger.info(
        "Queued mind map job filename=%s bytes=%d depth=%d branches=%d",
        filename,
        len(data),
        options.max_depth,
        options.max_branches,
        extra={"context": {"job_id": job.job_id}},
    )
    return UploadResponse(
        job_id=job.job_id,
        status=job.status.value,
        status_url=f"/mindmaps/{job.job_id}",
    )


@router.get(
    "/mindmaps/{job_id}",
    response_model=JobResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Unknown/expired job"},
        422: {"model": ErrorResponse, "description": "Generation failed (document error)"},
        502: {"model": ErrorResponse, "description": "Generation failed (LLM error)"},
    },
    summary="Poll job status and retrieve the result",
)
async def get_mindmap(job_id: str, store: JobStoreDep) -> Any:
    """Return progress, errors and (when completed) the generated mind map.

    Failed jobs preserve the original failure status code (422 for document
    problems, 502 for LLM problems, 500 for unexpected errors) so clients can
    distinguish retryable provider failures from bad input.
    """
    job = store.get(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    payload = JobResponse.model_validate(job.to_dict())
    if job.status == JobStatus.failed:
        status_code = int((job.error or {}).get("status_code", 500))
        if status_code < 400:
            status_code = 500
        return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
    return payload


@router.get(
    "/mindmaps/{job_id}/export",
    response_class=Response,
    responses={
        200: {"content": {"application/json": {}, "text/markdown": {}}},
        404: {"model": ErrorResponse, "description": "Unknown/expired job"},
        409: {"model": ErrorResponse, "description": "Job not completed"},
    },
    summary="Export a completed mind map",
)
async def export_mindmap(
    job_id: str,
    store: JobStoreDep,
    format: Literal["json", "markdown"] = "json",
) -> Response:
    """Download the result as canonical JSON or a Markdown outline."""
    job = store.get(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    if job.status != JobStatus.completed or not job.result:
        raise JobNotReadyError(job.status.value)

    if format == "json":
        content = export_json(job.result)
        media_type = "application/json"
        extension = "json"
    else:
        content = export_markdown(job.result)
        media_type = "text/markdown; charset=utf-8"
        extension = "md"

    stem = Path(job.filename).stem or "document"
    filename = f"{stem}-mindmap.{extension}"
    ascii_name = filename.encode("ascii", "ignore").decode() or f"mindmap.{extension}"
    headers = {
        "Content-Disposition": (
            f"attachment; filename=\"{ascii_name}\"; "
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )
    }
    return Response(content=content, media_type=media_type, headers=headers)
