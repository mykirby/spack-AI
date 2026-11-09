"""The agent loop, driven by a scripted fake provider (no network, no API key)."""

import json

from spack_ai.agent import Agent, Session
from spack_ai.llm.base import LLMResponse, ToolCall, ToolResult


class ScriptedProvider:
    name = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen_tools = None
        self.requests = []

    def complete(self, system, messages, tools):
        self.seen_tools = [t["name"] for t in tools]
        self.requests.append(list(messages))
        return self.turns.pop(0)

    def user_message(self, text):
        return {"role": "user", "content": text}

    def assistant_message(self, response):
        return {"role": "assistant", "content": response.raw_content}

    def tool_results_message(self, results: list[ToolResult]):
        return {"role": "user", "content": [r.__dict__ for r in results]}


def tool_turn(*calls):
    return LLMResponse("tool_use", "", [ToolCall(f"t{i}", n, a) for i, (n, a) in enumerate(calls)],
                       raw_content=[c[0] for c in calls])


def final(text):
    return LLMResponse("end_turn", text, [], raw_content=text)


def test_agent_runs_skills_and_logs(settings, fixtures):
    provider = ScriptedProvider([
        tool_turn(("analyze_build_system", {"path": str(fixtures / "cmake_project")}),
                  ("map_dependencies", {})),
        tool_turn(("draft_package_recipe", {"name": "heat-solver"}),
                  ("analyze_build_system", {"path": 42, "bogus": True})),
        tool_turn(("fetch_source", {"url": "https://example.org/x.tar.gz"})),
        final("Done."),
    ])
    agent = Agent(settings, provider=provider, sources=[fixtures])
    assert agent.send("Package the heat solver") == "Done."
    assert "analyze_build_system" in provider.seen_tools

    # Both results of a parallel turn come back in one message.
    results = provider.requests[2][-1]["content"]
    assert [r["tool_call_id"] for r in results] == ["t0", "t1"]
    assert not results[0]["is_error"] and json.loads(results[0]["content"])["files"]
    assert results[1]["is_error"] and "INVALID_INPUT" in results[1]["content"]

    # fetch_source needs approval; with no confirm callback it is declined.
    declined = provider.requests[3][-1]["content"][0]
    assert declined["is_error"] and "declined" in declined["content"]

    assert agent.ctx.state["recipe_name"] == "heat-solver"
    events = [e["event"] for e in Session.read(agent.session.path)]
    assert events[0] == "session_start" and "confirmation" in events
    assert events.count("tool_result") == 5 and events[-1] == "assistant"


def test_agent_stops_on_refusal_and_truncation(settings):
    refusal = LLMResponse("refusal", "", [], raw_content=[], stop_details="cyber: test")
    agent = Agent(settings, provider=ScriptedProvider([refusal]))
    assert "declined" in agent.send("hi")

    truncated = LLMResponse("max_tokens", "", [ToolCall("t", "save_package_recipe", {})],
                            raw_content=[])
    agent = Agent(settings, provider=ScriptedProvider([truncated]))
    assert "max_tokens" in agent.send("hi")
    assert agent.messages[-1]["role"] == "user"  # the partial tool call was not appended


def test_auto_approve_and_confirm(settings):
    calls = []
    provider = ScriptedProvider([
        tool_turn(("spack_command", {"args": ["install", "zlib"]})), final("ok")])
    agent = Agent(settings, provider=provider, confirm=lambda p: calls.append(p) or True)
    agent.send("install zlib")
    assert calls and "spack install zlib" in calls[0]
    result = provider.requests[1][-1]["content"][0]
    assert result["is_error"] and "not installed" in result["content"]  # approved, then ran
