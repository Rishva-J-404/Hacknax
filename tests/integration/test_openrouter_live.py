"""
tests.integration.test_openrouter_live
--------------------------------------
Optional live integration test against the OpenRouter API.
Skipped automatically when OPENROUTER_API_KEY is not set.
"""

from __future__ import annotations

import os
import pytest

from app.agent.qwen_client import OpenRouterQwenClient


@pytest.mark.skipif(
    not os.getenv("OPENROUTER_API_KEY"),
    reason="Live OpenRouter test requires OPENROUTER_API_KEY environment variable.",
)
def test_openrouter_live_connectivity_smoke():
    """Live smoke test verifying connectivity and structured JSON output from OpenRouter."""
    client = OpenRouterQwenClient()
    messages = [
        {"role": "system", "content": "You are a test assistant. Output only JSON."},
        {"role": "user", "content": "Return a JSON object with key 'status' set to 'ok'."},
    ]
    response = client.generate(messages)
    assert response is not None
    assert "status" in response.lower()
