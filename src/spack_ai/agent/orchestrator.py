"""The agent loop: model <-> skills, with validation, approval gates, and transcripts."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from spack_ai.agent.prompts import build_system_prompt
from spack_ai.agent.session import Session
from spack_ai.config import Settings
from spack_ai.llm import LLMProvider, LLMResponse, ToolCall, ToolResult, get_provider
from spack_ai.skills import all_skills
from spack_ai.skills.base import SkillContext, SkillError, format_validation_error

ConfirmFn = Callable[[str], bool]
EventFn = Callable[[str, dict[str, Any]], None]

DECLINED = (
    "The user declined this action. Continue without it, or ask the user how to proceed."
)


class Agent:
    def __init__(
        self,
        settings: Settings,
        provider: LLMProvider | None = None,
        session: Session | None = None,
        sources: list[Path] | None = None,
        confirm: ConfirmFn | None = None,
        on_event: EventFn | None = None,
    ):
        self.settings = settings
        self.session = session or Session(settings)
        self.ctx = SkillContext(
            settings, workspace=self.session.workspace, allowed_roots=list(sources or [])
        )
        if sources:
            self.ctx.state["source_root"] = str(sources[0].resolve())
        skill_classes = all_skills()
        self.skills = {name: cls(self.ctx) for name, cls in skill_classes.items()}
        self.tools = [cls.tool_definition() for cls in skill_classes.values()]
        self.system = build_system_prompt(settings, skill_classes, self.ctx.knowledge)
        self.provider = provider or get_provider(settings.llm)
        self.confirm = confirm
        self.on_event = on_event or (lambda kind, data: None)
        self.messages: list[dict[str, Any]] = []
        self.session.log(
            "session_start",
            model=settings.llm.model,
            sources=[str(s) for s in sources or []],
            workspace=str(self.session.workspace),
        )

    def send(self, text: str) -> str:
        """Run one user message to completion and return the final assistant text."""
        if self.ctx.state.get("source_root") and not self.messages:
            text = f"{text}\n\n(Source tree available at: {self.ctx.state['source_root']})"
        self.messages.append(self.provider.user_message(text))
        self.session.log("user", text=text)

        for _ in range(self.settings.agent.max_turns):
            response = self.provider.complete(self.system, self.messages, self.tools)
            self._log_response(response)

            if response.stop_reason == "refusal":
                return f"The model declined this request ({response.stop_details or 'no details'})."
            if response.stop_reason == "max_tokens" and response.tool_calls:
                # A truncated tool input must never run; drop the partial turn.
                return ("The response was cut off at llm.max_tokens while writing a tool call. "
                        "Raise llm.max_tokens in the config and retry.")

            self.messages.append(self.provider.assistant_message(response))
            if response.text:
                self.on_event("text", {"text": response.text})
            if response.stop_reason == "pause_turn":
                continue
            if not response.tool_calls:
                if response.stop_reason == "max_tokens":
                    return response.text + "\n\n[response truncated at llm.max_tokens]"
                return response.text

            results = [self._execute(call) for call in response.tool_calls]
            self.messages.append(self.provider.tool_results_message(results))

        return (f"Stopped after {self.settings.agent.max_turns} model turns without finishing. "
                "Send another message to continue.")

    # ------------------------------------------------------------------------------

    def _execute(self, call: ToolCall) -> ToolResult:
        self.on_event("tool_start", {"name": call.name, "input": call.input})
        self.session.log("tool_call", id=call.id, name=call.name, input=call.input)
        result = self._run_skill(call)
        self.session.log("tool_result", id=call.id, name=call.name,
                         content=result.content, is_error=result.is_error)
        self.on_event("tool_end", {"name": call.name, "is_error": result.is_error,
                                   "content": result.content})
        return result

    def _run_skill(self, call: ToolCall) -> ToolResult:
        skill = self.skills.get(call.name)
        if skill is None:
            return ToolResult(call.id, f"Unknown tool {call.name!r}.", is_error=True)
        try:
            params = skill.validate(call.input)
        except ValidationError as exc:
            return ToolResult(call.id, format_validation_error(call.input, exc), is_error=True)

        prompt = skill.confirmation_prompt(params)
        if prompt and not self.settings.agent.auto_approve:
            approved = bool(self.confirm and self.confirm(prompt))
            self.session.log("confirmation", name=call.name, prompt=prompt, approved=approved)
            if not approved:
                return ToolResult(call.id, DECLINED, is_error=True)

        try:
            return ToolResult(call.id, skill.run(params).to_tool_content())
        except (SkillError, OSError, ValueError, KeyError) as exc:
            return ToolResult(call.id, f"{type(exc).__name__}: {exc}", is_error=True)
        except Exception as exc:  # noqa: BLE001 - surface to the model, keep the session alive
            self.session.log("internal_error", name=call.name, traceback=traceback.format_exc())
            return ToolResult(call.id, f"Internal error in {call.name}: {exc}", is_error=True)

    def _log_response(self, response: LLMResponse) -> None:
        self.session.log(
            "assistant",
            text=response.text,
            stop_reason=response.stop_reason,
            tool_calls=[{"id": c.id, "name": c.name} for c in response.tool_calls],
            usage=response.usage,
            model=response.model,
        )
