"""LLM providers. The agent depends only on spack_ai.llm.base.LLMProvider."""

from __future__ import annotations

from spack_ai.config import LLMConfig
from spack_ai.llm.base import LLMProvider, LLMResponse, ToolCall, ToolResult

__all__ = ["LLMProvider", "LLMResponse", "ToolCall", "ToolResult", "get_provider"]


def get_provider(config: LLMConfig) -> LLMProvider:
    if config.provider == "anthropic":
        from spack_ai.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(config)
    # Register additional providers here, e.g. a locally served fine-tuned model:
    #   if config.provider == "local":
    #       from spack_ai.llm.local_provider import LocalProvider
    #       return LocalProvider(config)
    raise ValueError(f"unknown LLM provider: {config.provider!r}")
