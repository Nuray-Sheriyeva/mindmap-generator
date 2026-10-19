"""FastAPI dependencies backed by application state."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..config import Settings
from ..jobs.cache import ResultCache
from ..jobs.runner import JobRunner
from ..jobs.store import JobStore
from ..llm.base import LLMClient


def get_app_settings(request: Request) -> Settings:
    """Return the settings object created during application startup."""
    return request.app.state.settings


def get_job_store(request: Request) -> JobStore:
    """Return the configured job store."""
    return request.app.state.store


def get_result_cache(request: Request) -> ResultCache:
    """Return the configured result cache."""
    return request.app.state.cache


def get_runner(request: Request) -> JobRunner:
    """Return the singleton background job runner."""
    return request.app.state.runner


def get_llm(request: Request) -> LLMClient:
    """Return the configured LLM client."""
    return request.app.state.llm


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
JobStoreDep = Annotated[JobStore, Depends(get_job_store)]
CacheDep = Annotated[ResultCache, Depends(get_result_cache)]
RunnerDep = Annotated[JobRunner, Depends(get_runner)]
LLMDep = Annotated[LLMClient, Depends(get_llm)]
