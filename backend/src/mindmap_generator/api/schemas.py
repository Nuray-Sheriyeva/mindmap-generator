"""API request/response schemas (OpenAPI-facing)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..models import MindMapResult


class ErrorInfo(BaseModel):
    """Error payload returned by every failing endpoint."""

    code: str
    message: str
    status_code: int
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    error: ErrorInfo


class UploadResponse(BaseModel):
    """Immediate response to a successful upload."""

    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    status_url: str


class JobResponse(BaseModel):
    """Polling payload for a generation job."""

    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    stage: str | None
    stage_label: str | None
    stage_index: int
    total_stages: int
    progress: float
    filename: str
    file_hash: str
    cache_hit: bool
    error: ErrorInfo | None = None
    result: MindMapResult | None = None
    created_at: str
    updated_at: str


class HealthResponse(BaseModel):
    """Liveness/readiness payload."""

    status: Literal["ok"]
    app: str
    version: str
    environment: str
    llm_provider: str
    llm_model: str
    cache_enabled: bool
