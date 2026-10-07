"""
tests.test_qwen_client
----------------------
Unit tests for OpenRouterQwenClient and MockQwenClient.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest

from app.agent.qwen_client import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMResponseMalformedError,
    LLMTimeoutError,
    MockQwenClient,
    OpenRouterQwenClient,
)


def test_mock_client_canned_response():
    client = MockQwenClient(canned_response='{"status": "READY"}')
    res = client.generate([{"role": "user", "content": "What is revenue?"}])
    assert res == '{"status": "READY"}'
    assert client.call_count == 1
    assert len(client.last_messages) == 1


def test_mock_client_response_map():
    client = MockQwenClient(
        response_map={
            "revenue": '{"status": "READY", "intent": "REVENUE"}',
            "orders": '{"status": "READY", "intent": "ORDERS"}',
        }
    )
    res_rev = client.generate([{"role": "user", "content": "Calculate total revenue"}])
    assert '"intent": "REVENUE"' in res_rev

    res_ord = client.generate([{"role": "user", "content": "Count total orders"}])
    assert '"intent": "ORDERS"' in res_ord


def test_mock_client_default_fallback():
    client = MockQwenClient()
    res = client.generate([{"role": "user", "content": "any query"}])
    assert '"status": "READY"' in res
    assert '"required_tables"' in res


def test_openrouter_client_unconfigured_raises():
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=True):
        client = OpenRouterQwenClient(api_key="")
        assert not client.is_configured
        with pytest.raises(LLMConfigurationError) as exc_info:
            client.generate([{"role": "user", "content": "hello"}])
        assert "OPENROUTER_API_KEY is not configured" in str(exc_info.value)


def test_openrouter_client_never_leaks_api_key_in_errors():
    secret_key = "sk-or-v1-secret-super-sensitive-token-12345"
    client = OpenRouterQwenClient(api_key=secret_key)
    sanitized = client._sanitize_error(f"Error occurred while using {secret_key} token")
    assert secret_key not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized


@patch("httpx.Client")
def test_openrouter_client_401_auth_error(mock_httpx_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_httpx_cls.return_value.__enter__.return_value = mock_client

    client = OpenRouterQwenClient(api_key="test_key")
    with pytest.raises(LLMAuthenticationError) as exc_info:
        client.generate([{"role": "user", "content": "hello"}])
    assert "authentication failed" in str(exc_info.value).lower()


@patch("httpx.Client")
def test_openrouter_client_429_rate_limit(mock_httpx_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_httpx_cls.return_value.__enter__.return_value = mock_client

    client = OpenRouterQwenClient(api_key="test_key")
    with pytest.raises(LLMRateLimitError) as exc_info:
        client.generate([{"role": "user", "content": "hello"}])
    assert "rate limit" in str(exc_info.value).lower()


@patch("httpx.Client")
def test_openrouter_client_timeout(mock_httpx_cls):
    import httpx
    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")
    mock_httpx_cls.return_value.__enter__.return_value = mock_client

    client = OpenRouterQwenClient(api_key="test_key", timeout=1.0)
    with pytest.raises(LLMTimeoutError) as exc_info:
        client.generate([{"role": "user", "content": "hello"}])
    assert "timed out" in str(exc_info.value).lower()


@patch("httpx.Client")
def test_openrouter_client_malformed_json_response(mock_httpx_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = ValueError("Invalid JSON")
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_httpx_cls.return_value.__enter__.return_value = mock_client

    client = OpenRouterQwenClient(api_key="test_key")
    with pytest.raises(LLMResponseMalformedError) as exc_info:
        client.generate([{"role": "user", "content": "hello"}])
    assert "not valid json" in str(exc_info.value).lower()
