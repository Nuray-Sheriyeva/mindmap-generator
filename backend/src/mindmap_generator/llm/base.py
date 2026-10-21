"""Thin async LLM client interface used by the pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """Provider-agnostic interface for JSON-structured LLM calls.

    Implementations must return a parsed JSON object that matches the supplied
    JSON schema (or raise :class:`~mindmap_generator.errors.LLMError`).
    """

    provider: str = "unknown"
    model: str = "unknown"

    def configuration_error(self) -> str | None:
        """Return a human-readable configuration problem, if any.

        The graph checks this before starting expensive LLM work so the user
        gets a clear error instead of a generic "all calls failed" message.
        """
        return None

    @abstractmethod
    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str = "response",
    ) -> dict[str, Any]:
        """Run one structured-output completion."""

    async def aclose(self) -> None:
        """Release provider resources. Default: nothing to do."""
        return None
