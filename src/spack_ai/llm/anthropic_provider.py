"""Claude via the official Anthropic SDK."""

from __future__ import annotations

from typing import Any

import anthropic

from spack_ai.config import LLMConfig
from spack_ai.llm.base import LLMResponse, ToolCall, ToolResult

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# How many times to re-issue a request whose streamed tool input was unparseable JSON.
MAX_JSON_RETRIES = 2


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, config: LLMConfig, client: anthropic.Anthropic | None = None):
        self.config = config
        # Credentials resolve from ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or `ant auth login`.
        self.client = client or anthropic.Anthropic()

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        params: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            # The system prompt is stable for a whole session: cache it explicitly, and let
            # top-level automatic caching cover the growing conversation tail.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "cache_control": {"type": "ephemeral"},
            "messages": messages,
            # Stream tool inputs (whole package.py files) as they are generated. Inputs are
            # validated against each skill's pydantic model before anything runs.
            "tools": [{**tool, "eager_input_streaming": True} for tool in tools],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.config.effort},
        }
        if self.config.fallbacks:
            params["fallbacks"] = self.config.fallbacks
            params["betas"] = [FALLBACK_BETA]

        for attempt in range(MAX_JSON_RETRIES + 1):
            try:
                with self.client.beta.messages.stream(**params) as stream:
                    message = stream.get_final_message()
                break
            except ValueError:
                # The SDK could not parse a streamed tool input at all; there is no
                # tool_use id to answer, so re-issue the request.
                if attempt == MAX_JSON_RETRIES:
                    raise

        text = "".join(b.text for b in message.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, input=b.input if isinstance(b.input, dict) else {})
            for b in message.content
            if b.type == "tool_use"
        ]
        usage = message.usage.model_dump(exclude_none=True) if message.usage else {}
        details = message.stop_details
        return LLMResponse(
            stop_reason=message.stop_reason or "end_turn",
            text=text,
            tool_calls=calls,
            raw_content=message.content,
            usage=usage,
            model=message.model,
            stop_details=f"{details.category}: {details.explanation}" if details else None,
        )

    def user_message(self, text: str) -> dict[str, Any]:
        return {"role": "user", "content": text}

    def assistant_message(self, response: LLMResponse) -> dict[str, Any]:
        # Append the full content (thinking, fallback and tool_use blocks included):
        # the history must stay append-only for thinking blocks to remain valid.
        return {"role": "assistant", "content": response.raw_content}

    def tool_results_message(self, results: list[ToolResult]) -> dict[str, Any]:
        # All results for one assistant turn go back in a single user message.
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": r.tool_call_id,
                    "content": r.content,
                    **({"is_error": True} if r.is_error else {}),
                }
                for r in results
            ],
        }
