"""LLM configuration diagnostics (no network calls)."""

from __future__ import annotations

import pytest

from mindmap_generator.config import Settings
from mindmap_generator.errors import LLMError
from mindmap_generator.llm.mock import MockLLMClient
from mindmap_generator.llm.openai_compat import OpenAICompatibleClient


def test_openai_client_reports_missing_key_without_network() -> None:
    settings = Settings(llm_provider="openai", llm_api_key=None)
    client = OpenAICompatibleClient(settings)
    problem = client.configuration_error()
    assert problem is not None
    assert "No LLM API key configured" in problem
    assert "LLM_PROVIDER=mock" in problem


@pytest.mark.asyncio
async def test_openai_client_raises_clear_error_before_request() -> None:
    client = OpenAICompatibleClient(Settings(llm_provider="openai", llm_api_key=None))
    with pytest.raises(LLMError) as excinfo:
        await client.generate_json(
            system_prompt="x",
            user_prompt="y",
            schema={"type": "object"},
            schema_name="test",
        )
    assert "No LLM API key configured" in excinfo.value.message
    assert excinfo.value.status_code == 502


def test_mock_client_is_configured() -> None:
    client = MockLLMClient(Settings(llm_provider="mock"))
    assert client.configuration_error() is None
