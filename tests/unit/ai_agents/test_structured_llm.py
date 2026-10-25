"""Unit tests for ai_agents/structured_llm.py — ABC + 3 impls + vanilla JSON prompt."""
import json

import pytest
from pydantic import BaseModel

from ai_agents.base import AIAgent, AgentResult
from ai_agents.errors import AllAgentsFailedError, StructuredLLMParseError
from ai_agents.structured_llm import (
    AgentStructuredLLM,
    ChainedStructuredLLM,
    StructuredLLM,
    _build_json_prompt,
)


class Classification(BaseModel):
    category: str
    confidence: float


class _StubAgent(AIAgent):
    name = "stub"
    cost_tier = "free"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def run(self, task):
        return AgentResult(True, "", [], "", None, 0.1)

    def chat(self, prompt, timeout_s=60):
        self.calls.append(prompt)
        return self._responses.pop(0)

    def healthcheck(self):
        return True


def test_structured_llm_is_abc():
    with pytest.raises(TypeError):
        StructuredLLM()  # type: ignore[abstract]


def test_build_json_prompt_includes_schema_and_question():
    prompt = _build_json_prompt("Is this simple?", Classification)
    assert "Classification" in prompt or "category" in prompt  # schema dumped
    assert "Is this simple?" in prompt
    assert "ONLY" in prompt.upper() or "only" in prompt  # directive present


def test_agent_structured_llm_parses_valid_json():
    agent = _StubAgent(['{"category": "simple", "confidence": 0.9}'])
    sllm = AgentStructuredLLM(agent)
    out = sllm.ask("Is this simple?", Classification)
    assert out.category == "simple"
    assert out.confidence == 0.9


def test_agent_structured_llm_retries_on_invalid_then_succeeds():
    agent = _StubAgent([
        "not json at all",
        '{"category": "x", "confidence": 0.5}',
    ])
    sllm = AgentStructuredLLM(agent)
    out = sllm.ask("Q", Classification, max_retries=1)
    assert out.category == "x"
    assert len(agent.calls) == 2  # original + 1 retry
    # Second call must be the correction prompt, not the original.
    assert agent.calls[0] != agent.calls[1]
    assert "failed validation" in agent.calls[1].lower()


def test_agent_structured_llm_raises_after_retries_exhausted():
    agent = _StubAgent(["bad", "still bad", "also bad"])
    sllm = AgentStructuredLLM(agent)
    with pytest.raises(StructuredLLMParseError):
        sllm.ask("Q", Classification, max_retries=2)


def test_agent_structured_llm_strips_code_fences():
    agent = _StubAgent(['```json\n{"category":"a","confidence":0.1}\n```'])
    sllm = AgentStructuredLLM(agent)
    out = sllm.ask("Q", Classification)
    assert out.category == "a"


def test_chained_structured_llm_falls_through_on_failure():
    failing_agent = _StubAgent(["garbage", "still garbage", "more garbage"])
    good_agent = _StubAgent(['{"category": "ok", "confidence": 1.0}'])
    chain = ChainedStructuredLLM([AgentStructuredLLM(failing_agent), AgentStructuredLLM(good_agent)])
    out = chain.ask("Q", Classification)
    assert out.category == "ok"


def test_chained_structured_llm_raises_when_all_fail():
    a = _StubAgent(["x", "x", "x"])
    b = _StubAgent(["y", "y", "y"])
    chain = ChainedStructuredLLM([AgentStructuredLLM(a), AgentStructuredLLM(b)])
    with pytest.raises(AllAgentsFailedError):
        chain.ask("Q", Classification)


def test_chained_structured_llm_falls_through_on_non_agent_error():
    """Regression test for I1. Providers may raise non-AIAgentError exceptions
    (ConnectionError, OSError, etc.). The chain must not let those tear through
    — the whole point of the chain is to try the next provider on any failure."""

    class _ExplodingLLM(StructuredLLM):
        def ask(self, prompt, schema, max_retries=2):
            raise ConnectionError("simulated network failure")

    good_agent = _StubAgent(['{"category": "ok", "confidence": 1.0}'])
    chain = ChainedStructuredLLM([_ExplodingLLM(), AgentStructuredLLM(good_agent)])
    out = chain.ask("Q", Classification)
    assert out.category == "ok"


def test_chained_structured_llm_empty_providers_raises():
    with pytest.raises(ValueError, match="at least one provider"):
        ChainedStructuredLLM([])
