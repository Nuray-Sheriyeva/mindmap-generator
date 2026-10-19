"""Background job execution: cache lookup, graph invocation, job updates."""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from typing import Any

from ..config import Settings
from ..errors import GenerationError, MindMapError
from ..graph.state import PipelineState
from ..llm.base import LLMClient
from ..logging_config import job_id_var
from ..models import GenerationOptions
from .cache import ResultCache, cache_key
from .store import JobStore

logger = logging.getLogger(__name__)


class JobRunner:
    """Executes one generation job against the compiled LangGraph."""

    def __init__(
        self,
        *,
        settings: Settings,
        graph: Any,
        llm: LLMClient,
        store: JobStore,
        cache: ResultCache,
    ) -> None:
        self.settings = settings
        self.graph = graph
        self.llm = llm
        self.store = store
        self.cache = cache

    async def run(
        self,
        *,
        job_id: str,
        pdf_bytes: bytes,
        filename: str,
        file_hash: str,
        options: GenerationOptions,
    ) -> None:
        """Run the pipeline and record completion/failure on the job."""
        token = job_id_var.set(job_id)
        started_at = time.time()
        try:
            key = cache_key(
                file_hash,
                max_depth=options.max_depth,
                max_branches=options.max_branches,
                language=options.language,
            )
            if self.settings.cache_enabled:
                cached = self.cache.get(key)
                if cached is not None:
                    result = copy.deepcopy(cached)
                    result.setdefault("meta", {})["cache_hit"] = True
                    self.store.complete(job_id, result, cache_hit=True)
                    logger.info("Job served from cache hash=%s", file_hash[:12])
                    return

            initial: PipelineState = {
                "job_id": job_id,
                "pdf_bytes": pdf_bytes,
                "filename": filename,
                "options": options.model_dump(),
                "started_at": started_at,
            }
            output = await self.graph.ainvoke(initial, config={"recursion_limit": 30})
            result = output.get("result")
            if not isinstance(result, dict):
                raise GenerationError("The pipeline finished without producing a result.")

            if self.settings.cache_enabled:
                self.cache.put(key, copy.deepcopy(result))
            self.store.complete(job_id, result)
            logger.info(
                "Job completed nodes=%s depth=%s elapsed_ms=%d",
                (result.get("meta") or {}).get("node_count"),
                (result.get("meta") or {}).get("depth"),
                int((time.time() - started_at) * 1000),
            )
        except MindMapError as exc:
            self.store.fail(job_id, exc.to_dict())
            logger.warning("Job failed code=%s message=%s", exc.code, exc.message)
        except asyncio.CancelledError:
            self.store.fail(
                job_id,
                {
                    "code": "cancelled",
                    "message": "The generation job was cancelled.",
                    "status_code": 500,
                    "details": {},
                },
            )
            raise
        except Exception as exc:  # pragma: no cover - last-resort safety net
            logger.exception("Unexpected job failure")
            self.store.fail(
                job_id,
                {
                    "code": "internal_error",
                    "message": "Unexpected internal error while generating the mind map.",
                    "status_code": 500,
                    "details": {"error": str(exc)[:300]},
                },
            )
        finally:
            job_id_var.reset(token)
