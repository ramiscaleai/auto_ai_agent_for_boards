"""Unit tests for ai_agents/base.py — dataclass invariants + ABC enforcement."""
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ai_agents.base import AIAgent, AgentResult, AgentTask


def test_agent_task_defaults():
    task = AgentTask(prompt="hello", cwd=Path("/tmp"))
    assert task.prompt == "hello"
    assert task.cwd == Path("/tmp")
    assert task.allowed_tools == frozenset({"read", "write", "bash"})
    assert task.timeout_s == 1800


def test_agent_task_is_frozen():
    task = AgentTask(prompt="x", cwd=Path("/tmp"))
    with pytest.raises(FrozenInstanceError):
        task.prompt = "mutated"  # type: ignore[misc]


def test_agent_result_required_fields():
    result = AgentResult(
        success=True,
        summary="ok",
        files_changed=[Path("a.py")],
        output="stdout here",
        cost_usd=0.12,
        duration_s=5.0,
    )
    assert result.success is True
    assert result.cost_usd == 0.12
    assert result.error is None
    assert result.questions is None


def test_agent_result_failure_shape():
    result = AgentResult(
        success=False,
        summary="failed",
        files_changed=[],
        output="oops",
        cost_usd=None,
        duration_s=1.0,
        error="AgentToolError: bad flag",
    )
    assert result.success is False
    assert result.error == "AgentToolError: bad flag"


def test_aiagent_abc_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        AIAgent()  # type: ignore[abstract]


class _FakeAgent(AIAgent):
    name = "fake"
    cost_tier = "free"

    def run(self, task):
        return AgentResult(True, "ran", [], "", None, 0.1)

    def chat(self, prompt, timeout_s=60):
        return "hi"

    def healthcheck(self):
        return True


def test_fake_agent_satisfies_abc():
    agent = _FakeAgent()
    assert agent.name == "fake"
    assert agent.cost_tier == "free"
    assert agent.healthcheck() is True
