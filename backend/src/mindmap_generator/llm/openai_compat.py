"""OpenAI-compatible structured-output client (works with OpenAI, DeepSeek,
OpenRouter, Groq, Together, local vLLM/Ollama endpoints, etc.)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from ..config import Settings
from ..errors import LLMError
from .base import LLMClient

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def extract_json_object(content: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences and prose."""
    text = (content or "").strip()
    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object at the top level")
    return parsed


class OpenAICompatibleClient(LLMClient):
    """Calls ``POST {base_url}/chat/completions`` with JSON-schema output."""

    provider = "openai"

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self.model = settings.llm_model
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=settings.llm_timeout_seconds)

    async def _post(self, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        url = f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"
        last_error: Exception | None = None
        for attempt in range(self._settings.llm_max_retries + 1):
            try:
                response = await self._client.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self._settings.llm_max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise LLMError(f"Could not reach the LLM provider: {exc}") from exc
            retryable = response.status_code in _RETRYABLE_STATUS
            if retryable and attempt < self._settings.llm_max_retries:
                retry_after = response.headers.get("retry-after")
                delay = (
                    float(retry_after)
                    if retry_after and retry_after.isdigit()
                    else 0.5 * (2**attempt)
                )
                logger.warning(
                    "LLM request retryable status=%s attempt=%d delay=%.1fs",
                    response.status_code,
                    attempt + 1,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            return response
        raise LLMError(f"Could not reach the LLM provider: {last_error}")

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        schema_name: str = "response",
    ) -> dict[str, Any]:
        """Call the provider and return a parsed JSON object."""
        settings = self._settings
        if not settings.llm_api_key:
            raise LLMError(
                "No LLM API key configured. Set API_KEY in the backend environment "
                "(or use LLM_PROVIDER=mock for an offline demo)."
            )

        system = system_prompt
        body: dict[str, Any] = {
            "model": settings.llm_model,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_output_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
        }
        if settings.llm_json_mode == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": re.sub(r"[^a-zA-Z0-9_-]", "_", schema_name),
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            system += (
                "\n\nReturn only a JSON object that conforms to this JSON schema:\n"
                + json.dumps(schema, ensure_ascii=False)
            )
            body["messages"][0]["content"] = system
            body["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        response = await self._post(body, headers)

        if response.status_code >= 400:
            detail = response.text[:600]
            raise LLMError(
                f"LLM provider returned HTTP {response.status_code}.",
                details={"status": response.status_code, "body": detail},
            )

        try:
            payload = response.json()
            choices = payload.get("choices") or []
            content = choices[0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("The LLM provider returned an unexpected response shape.") from exc

        usage = payload.get("usage") or {}
        logger.info(
            "LLM completion model=%s prompt_tokens=%s completion_tokens=%s",
            settings.llm_model,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )

        try:
            return extract_json_object(str(content))
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(
                "The LLM response was not valid JSON.",
                details={"preview": str(content)[:500]},
            ) from exc

    async def aclose(self) -> None:
        """Close the underlying HTTP client when this instance owns it."""
        if self._owns_client:
            await self._client.aclose()
