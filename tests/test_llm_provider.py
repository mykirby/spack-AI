"""The Claude provider's wire request, captured with a mock transport (no network)."""

import json

import anthropic
import httpx2
import pytest

from spack_ai.config import LLMConfig
from spack_ai.llm.anthropic_provider import FALLBACK_BETA, AnthropicProvider
from spack_ai.llm.base import ToolResult


def capture_request(config: LLMConfig) -> tuple[dict, dict]:
    captured = {}

    def handler(request):
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx2.Response(
            400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "x"}}
        )

    client = anthropic.Anthropic(
        api_key="test", max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    tool = {"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}
    with pytest.raises(anthropic.BadRequestError):
        AnthropicProvider(config, client=client).complete(
            "SYSTEM", [{"role": "user", "content": "hi"}], [tool])
    return captured["headers"], captured["body"]


def test_request_shape():
    headers, body = capture_request(LLMConfig())
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"][0]["eager_input_streaming"] is True
    assert body["fallbacks"] == "default" and FALLBACK_BETA in headers["anthropic-beta"]


def test_fallbacks_can_be_disabled():
    headers, body = capture_request(LLMConfig(fallbacks=None))
    assert "fallbacks" not in body and "anthropic-beta" not in headers


def test_tool_results_are_batched():
    message = AnthropicProvider(LLMConfig(), client=anthropic.Anthropic(api_key="x")) \
        .tool_results_message([ToolResult("a", "ok"), ToolResult("b", "bad", is_error=True)])
    assert message["role"] == "user" and len(message["content"]) == 2
    assert "is_error" not in message["content"][0] and message["content"][1]["is_error"]
