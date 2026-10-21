"""FastAPI application factory, lifespan wiring and global error handling."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import Settings, get_settings
from ..errors import MindMapError
from ..graph.builder import build_graph
from ..jobs.cache import InMemoryResultCache, ResultCache
from ..jobs.runner import JobRunner
from ..jobs.store import InMemoryJobStore, JobStore
from ..llm.base import LLMClient
from ..llm.factory import create_llm
from ..logging_config import configure_logging
from .routes import router

logger = logging.getLogger(__name__)

DESCRIPTION = """
Turn any text-based PDF into an interactive, concept-first mind map.

* Upload a PDF → background LangGraph pipeline (parse → classify sections →
  chunk → extract concept cards → cluster ideas → validate/repair → finalize)
* Category nodes stay clean; leaves carry a visible, grounded explanation and
  source pages
* Poll the job for stage-by-stage progress
* Export as JSON or a Markdown outline

Generation requires an LLM provider (set `API_KEY`) or `LLM_PROVIDER=mock` for
an offline heuristic demo. No API keys are exposed by any endpoint.
"""


def _error_payload(
    code: str,
    message: str,
    status_code: int,
    details: Any | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "status_code": status_code,
            "details": details or {},
        }
    }


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(MindMapError)
    async def mindmap_error_handler(request: Request, exc: MindMapError) -> JSONResponse:
        logger.warning(
            "Request failed path=%s code=%s message=%s",
            request.url.path,
            exc.code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.code, exc.message, exc.status_code, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = []
        for error in exc.errors():
            details.append(
                {
                    "loc": [str(part) for part in error.get("loc", [])],
                    "msg": error.get("msg", "Invalid value"),
                    "type": error.get("type", "value_error"),
                }
            )
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                "validation_error", "Request validation failed.", 422, {"errors": details}
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(
                "http_error",
                str(exc.detail),
                exc.status_code,
                {"path": request.url.path},
            ),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error path=%s", request.url.path)
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                "internal_error",
                "An unexpected internal error occurred.",
                500,
            ),
        )


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    store: JobStore | None = None,
    cache: ResultCache | None = None,
) -> FastAPI:
    """Create the application; dependencies can be injected for tests."""
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(app_settings.log_level)
        app.state.settings = app_settings
        app.state.store = store or InMemoryJobStore(ttl_minutes=app_settings.job_ttl_minutes)
        app.state.cache = cache or InMemoryResultCache(
            max_entries=app_settings.cache_max_entries
        )
        app.state.llm = llm or create_llm(app_settings)
        # Compiled once and reused across every request/job.
        app.state.graph = build_graph(app_settings, app.state.llm, app.state.store)
        app.state.runner = JobRunner(
            settings=app_settings,
            graph=app.state.graph,
            llm=app.state.llm,
            store=app.state.store,
            cache=app.state.cache,
        )
        configuration_error = app.state.llm.configuration_error()
        if configuration_error:
            logger.warning("LLM provider is not configured: %s", configuration_error)
        logger.info(
            "Application started provider=%s model=%s",
            app_settings.llm_provider,
            app_settings.llm_model,
        )
        try:
            yield
        finally:
            await app.state.llm.aclose()
            logger.info("Application stopped")

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "mindmaps", "description": "Upload, poll and export mind maps."},
        ],
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.include_router(router)
    _register_exception_handlers(app)
    return app


app = create_app()
