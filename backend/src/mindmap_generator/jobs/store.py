"""In-memory job store behind a small interface.

The MVP is intentionally single-process. Replace :class:`InMemoryJobStore`
with Redis/Postgres for multi-worker deployments without touching the API.
"""

from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from ..graph.state import STAGE_LABELS, stage_position


class JobStatus(StrEnum):
    """Lifecycle states exposed by the API."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


@dataclass
class Job:
    """A generation job and its progress/result."""

    job_id: str
    filename: str
    file_hash: str
    status: JobStatus = JobStatus.pending
    stage: str | None = "queued"
    stage_index: int = 0
    total_stages: int = 6
    progress: float = 0.0
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    cache_hit: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the job for API responses."""
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "stage": self.stage,
            "stage_label": STAGE_LABELS.get(self.stage or "", self.stage),
            "stage_index": self.stage_index,
            "total_stages": self.total_stages,
            "progress": self.progress,
            "filename": self.filename,
            "file_hash": self.file_hash,
            "cache_hit": self.cache_hit,
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


def new_job_id() -> str:
    """Generate a URL-safe job identifier."""
    return uuid.uuid4().hex


class JobStore(ABC):
    """Persistence interface for jobs."""

    @abstractmethod
    def create(self, filename: str, file_hash: str, *, job_id: str | None = None) -> Job: ...

    @abstractmethod
    def get(self, job_id: str) -> Job | None: ...

    @abstractmethod
    def update_stage(self, job_id: str, stage: str) -> None: ...

    @abstractmethod
    def complete(
        self, job_id: str, result: dict[str, Any], *, cache_hit: bool = False
    ) -> None: ...

    @abstractmethod
    def fail(self, job_id: str, error: dict[str, Any]) -> None: ...


class InMemoryJobStore(JobStore):
    """Thread-safe, TTL-bounded in-memory job store."""

    def __init__(self, ttl_minutes: int = 60) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self.ttl = timedelta(minutes=max(1, ttl_minutes))

    def _purge_locked(self) -> None:
        now = datetime.now(UTC)
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if now - job.updated_at > self.ttl
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)

    def create(self, filename: str, file_hash: str, *, job_id: str | None = None) -> Job:
        """Create a pending job."""
        with self._lock:
            self._purge_locked()
            identifier = job_id or new_job_id()
            job = Job(job_id=identifier, filename=filename, file_hash=file_hash)
            self._jobs[identifier] = job
            return job

    def get(self, job_id: str) -> Job | None:
        """Fetch a job, evicting it when its TTL has elapsed."""
        with self._lock:
            self._purge_locked()
            return self._jobs.get(job_id)

    def update_stage(self, job_id: str, stage: str) -> None:
        """Mark a job running and record pipeline progress."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            index, total, progress = stage_position(stage)
            job.status = JobStatus.running
            job.stage = stage
            job.stage_index = index
            job.total_stages = total
            job.progress = progress
            job.updated_at = datetime.now(UTC)

    def complete(
        self, job_id: str, result: dict[str, Any], *, cache_hit: bool = False
    ) -> None:
        """Attach a result and mark the job completed."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = JobStatus.completed
            job.stage = "finalize"
            job.stage_index = job.total_stages
            job.progress = 1.0
            job.result = result
            job.cache_hit = cache_hit
            job.error = None
            job.updated_at = datetime.now(UTC)

    def fail(self, job_id: str, error: dict[str, Any]) -> None:
        """Record a terminal failure."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = JobStatus.failed
            job.error = error
            job.updated_at = datetime.now(UTC)

    def clear(self) -> None:
        """Remove all jobs (test helper)."""
        with self._lock:
            self._jobs.clear()
