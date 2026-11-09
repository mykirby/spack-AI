"""Provider-neutral interface the agent loop talks to.

The agent never imports a vendor SDK. A provider turns (system prompt, history, tool
definitions) into an `LLMResponse` and knows how to append its own turn and tool
results to the history in its native format. To serve the project's own trained
model, implement this protocol and register it in spack_ai.llm.get_provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class LLMResponse:
    # "end_turn" | "tool_use" | "max_tokens" | "refusal" | "pause_turn" | provider-specific
    stop_reason: str
    text: str
    tool_calls: list[ToolCall]
    # Provider-native assistant content, appended to history verbatim.
    raw_content: Any
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    stop_details: str | None = None


class LLMProvider(Protocol):
    name: str

    def complete(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...

    def user_message(self, text: str) -> dict[str, Any]: ...

    def assistant_message(self, response: LLMResponse) -> dict[str, Any]: ...

    def tool_results_message(self, results: list[ToolResult]) -> dict[str, Any]: ...
