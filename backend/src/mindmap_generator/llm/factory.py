"""LLM client factory."""

from __future__ import annotations

from ..config import Settings
from .base import LLMClient
from .mock import MockLLMClient
from .openai_compat import OpenAICompatibleClient


def create_llm(settings: Settings) -> LLMClient:
    """Instantiate the configured provider.

    ``openai`` means any OpenAI-compatible chat-completions endpoint (configure
    ``LLM_BASE_URL``/``LLM_MODEL``). ``mock`` is an offline heuristic demo mode.
    """
    if settings.llm_provider == "mock":
        return MockLLMClient(settings)
    return OpenAICompatibleClient(settings)
