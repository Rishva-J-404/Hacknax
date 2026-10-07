"""
app.agent.qwen_client
---------------------
OpenRouter LLM client abstraction and deterministic mock client for ProofLens.

CORE PRINCIPLES (PROOFLENS_MASTER_CONTEXT.md §2, §9):
    LLM PROPOSES.
    CODE COMPUTES.
    VERIFICATION DECIDES.

SECURITY & SAFETY:
    - Never log or leak OPENROUTER_API_KEY in errors, logs, or proof cards.
    - API keys must come from environment variables or explicit parameters.
    - Deterministic generation settings (temperature=0).
    - Structured JSON output support.
    - Clean custom exceptions for network, authentication, and rate-limiting issues.
    - Mock client provided for deterministic, offline testing without network access.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
import os
import re
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Exceptions (Secure — No API Key Leakage)
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Base exception for LLM client operations."""
    pass


class LLMConfigurationError(LLMError):
    """Raised when required configuration (e.g. API key) is missing."""
    pass


class LLMAuthenticationError(LLMError):
    """Raised on HTTP 401 Unauthorized from OpenRouter."""
    pass


class LLMRateLimitError(LLMError):
    """Raised on HTTP 429 Too Many Requests from OpenRouter."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when an OpenRouter request exceeds the timeout threshold."""
    pass


class LLMAPIError(LLMError):
    """Raised when OpenRouter returns an unexpected HTTP error code."""
    pass


class LLMResponseMalformedError(LLMError):
    """Raised when the LLM response is empty or cannot be parsed as expected."""
    pass


# ---------------------------------------------------------------------------
# Provider Interface
# ---------------------------------------------------------------------------

class LLMClient(ABC):
    """Abstract interface for LLM completion providers."""

    @abstractmethod
    def generate(
        self,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """
        Send chat messages to the LLM and return the assistant text response.

        Parameters:
            messages: List of chat messages with 'role' and 'content'.
            response_schema: Optional JSON schema for structured output.
            temperature: Generation temperature (defaults to 0.0 for determinism).
            max_tokens: Maximum tokens in response.

        Returns:
            The raw text completion from the model.
        """
        pass


# ---------------------------------------------------------------------------
# OpenRouter Qwen Client
# ---------------------------------------------------------------------------

class OpenRouterQwenClient(LLMClient):
    """
    OpenRouter API client targeting Qwen models.
    Operates with temperature=0 and JSON formatting.
    """

    DEFAULT_BASE_URL: str = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL: str = "qwen/qwen-2.5-72b-instruct"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        http_referer: str | None = None,
        app_name: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.model = model or os.getenv("QWEN_MODEL") or self.DEFAULT_MODEL
        self.base_url = (
            base_url or os.getenv("OPENROUTER_BASE_URL") or self.DEFAULT_BASE_URL
        ).rstrip("/")
        self.http_referer = (
            http_referer
            or os.getenv("OPENROUTER_HTTP_REFERER")
            or "https://github.com/ProofLens"
        )
        self.app_name = (
            app_name or os.getenv("OPENROUTER_APP_NAME") or "ProofLens"
        )
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is present."""
        return bool(self._api_key and self._api_key.strip())

    def generate(
        self,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        if not self.is_configured:
            raise LLMConfigurationError(
                "OPENROUTER_API_KEY is not configured. Provide an API key or configure .env."
            )

        headers = {
            "Authorization": f"Bearer {self._api_key.strip()}",
            "HTTP-Referer": self.http_referer,
            "X-Title": self.app_name,
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        # Enable structured JSON output where applicable
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "analysis_plan",
                    "strict": True,
                    "schema": response_schema,
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}

        endpoint = f"{self.base_url}/chat/completions"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(endpoint, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"OpenRouter request timed out after {self.timeout}s."
            ) from None
        except httpx.RequestError as exc:
            # Strip any accidental secrets from error strings
            clean_err = self._sanitize_error(str(exc))
            raise LLMAPIError(f"Network error communicating with OpenRouter: {clean_err}") from None

        if response.status_code == 401:
            raise LLMAuthenticationError(
                "OpenRouter authentication failed (HTTP 401). Check OPENROUTER_API_KEY."
            )
        if response.status_code == 429:
            raise LLMRateLimitError(
                "OpenRouter rate limit or quota exceeded (HTTP 429)."
            )
        if response.status_code != 200:
            clean_text = self._sanitize_error(response.text[:200])
            raise LLMAPIError(
                f"OpenRouter returned HTTP {response.status_code}: {clean_text}"
            )

        try:
            data = response.json()
        except Exception:
            raise LLMResponseMalformedError("OpenRouter response was not valid JSON.")

        choices = data.get("choices", [])
        if not choices:
            raise LLMResponseMalformedError("OpenRouter returned empty choices list.")

        content = choices[0].get("message", {}).get("content", "")
        if not content or not content.strip():
            raise LLMResponseMalformedError("OpenRouter returned empty message content.")

        return content.strip()

    def _sanitize_error(self, message: str) -> str:
        """Ensure no API key snippet leaks in error descriptions."""
        if self._api_key and len(self._api_key) > 4:
            return message.replace(self._api_key, "[REDACTED_API_KEY]")
        return message


# ---------------------------------------------------------------------------
# Deterministic Mock Client for Tests and Offline Mode
# ---------------------------------------------------------------------------

class MockQwenClient(LLMClient):
    """
    Deterministic mock LLM client for testing without network requests or API keys.
    Can be configured with fixed responses, key-value mappings, or response callbacks.
    """

    def __init__(
        self,
        canned_response: str | dict[str, Any] | None = None,
        response_map: dict[str, str | dict[str, Any]] | None = None,
    ) -> None:
        self.call_count: int = 0
        self.last_messages: list[dict[str, str]] = []
        self.canned_response = canned_response
        self.response_map = response_map or {}

    def set_response(self, response: str | dict[str, Any]) -> None:
        """Set a single canned response for all subsequent calls."""
        self.canned_response = response

    def generate(
        self,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        self.call_count += 1
        self.last_messages = list(messages)

        # 1. Check for question matching in response_map
        user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_content = m.get("content", "")
                break

        for query_key, resp in self.response_map.items():
            if query_key.lower() in user_content.lower():
                if isinstance(resp, dict):
                    return json.dumps(resp)
                return str(resp)

        # 2. Use canned response if set
        if self.canned_response is not None:
            if isinstance(self.canned_response, dict):
                return json.dumps(self.canned_response)
            return str(self.canned_response)

        # 3. Default fallback response: valid minimal plan JSON
        default_plan = {
            "question": user_content[:100] or "Default mock question",
            "status": "READY",
            "required_tables": ["data"],
            "required_columns": [{"table": "data", "column": "amount"}],
            "aggregation": {
                "column": {"table": "data", "column": "amount"},
                "operation": "sum",
                "unit": "INR",
            },
            "filters": [],
            "join_keys": [],
            "group_by": [],
            "analysis_intent": "SUM_AMOUNT",
            "assumptions": ["Mock analysis plan for testing"],
            "ambiguity_flags": [],
        }
        return json.dumps(default_plan)
