"""Unit tests for ai_agents/runner.py — fallback chain, budget short-circuit, logging."""
from pathlib import Path

import pytest

from ai_agents.base import AIAgent, AgentResult, AgentTask
from ai_agents.cost_guard import CostGuard
from ai_agents.errors import AgentToolError, AllAgentsFailedError, BudgetExceededError
from ai_agents.runner import AgentRunner
from ai_agents.tracing import NoOpTracer


class _FakeReg:
    def __init__(self, chain: list[AIAgent]) -> None:
        self._chain = chain

    def coding_chain(self) -> list[AIAgent]:
        return self._chain


class _OKAgent(AIAgent):
    def __init__(self, name: str, cost_tier: str = "free", cost_usd: float | None = None) -> None:
        self.name = name
        self.cost_tier = cost_tier
        self._cost = cost_usd

    def run(self, task):
        return AgentResult(True, f"{self.name} ok", [], "", self._cost, 0.1)

    def chat(self, prompt, timeout_s=60):
        return ""

    def healthcheck(self):
        return True


class _FailAgent(_OKAgent):
    def run(self, task):
        raise AgentToolError(f"{self.name} fail", context={"agent_name": self.name})


def _runner(chain, tmp_path: Path, per_task=1.00, daily=10.00):
    reg = _FakeReg(chain)
    guard = CostGuard(per_task_cap_usd=per_task, daily_cap_usd=daily, state_path=tmp_path / "s.json")
    return AgentRunner(registry=reg, cost_guard=guard, tracer=NoOpTracer())


def test_first_agent_success_returns_immediately(tmp_path):
    chain = [_OKAgent("codex"), _OKAgent("gemini")]
    runner = _runner(chain, tmp_path)
    result = runner.run(AgentTask(prompt="p", cwd=tmp_path))
    assert result.success
    assert result.summary == "codex ok"


def test_first_fails_second_succeeds(tmp_path):
    chain = [_FailAgent("codex"), _OKAgent("gemini")]
    result = _runner(chain, tmp_path).run(AgentTask(prompt="p", cwd=tmp_path))
    assert result.summary == "gemini ok"


def test_all_fail_raises_all_agents_failed(tmp_path):
    chain = [_FailAgent("a"), _FailAgent("b")]
    with pytest.raises(AllAgentsFailedError) as exc_info:
        _runner(chain, tmp_path).run(AgentTask(prompt="p", cwd=tmp_path))
    # Order must match the chain.
    assert exc_info.value.context["attempted"] == ["a", "b"]
    # Each error entry must name the agent that produced it.
    errors = exc_info.value.context["errors"]
    assert any(e.startswith("a:") for e in errors)
    assert any(e.startswith("b:") for e in errors)


def test_budget_exceeded_short_circuits_chain(tmp_path):
    # Both free agents fail; openrouter's precheck tripwire fires on daily cap;
    # claude must NOT be reached (chain must stop at the paid precheck).
    claude = _OKAgent("claude", cost_tier="high", cost_usd=0.50)
    claude_reached: list[bool] = []

    def _spy_run(task):  # wraps claude.run to detect invocation
        claude_reached.append(True)
        return AgentResult(True, "claude ok", [], "", 0.50, 0.1)

    claude.run = _spy_run  # type: ignore[method-assign]
    chain = [
        _FailAgent("codex", cost_tier="free"),
        _FailAgent("gemini", cost_tier="free"),
        _OKAgent("openrouter", cost_tier="medium", cost_usd=0.10),
        claude,
    ]
    # per_task=10.00 lets the seed record(5.0) persist without tripping per-task;
    # daily=0.00 ensures the paid openrouter precheck fires on the daily cap.
    runner = _runner(chain, tmp_path, per_task=10.00, daily=0.00)
    guard = runner._cost_guard  # type: ignore[attr-defined]
    guard.record(AgentResult(True, "", [], "", 5.0, 1.0))  # well over daily=0 cap
    with pytest.raises(BudgetExceededError):
        runner.run(AgentTask(prompt="p", cwd=tmp_path))
    assert not claude_reached, "claude must not be reached after BudgetExceededError"


def test_result_success_false_advances_chain(tmp_path):
    """AIAgent contract allows returning AgentResult(success=False, error=...)
    without raising. Runner must treat that as a failure and try the next agent."""

    class _SoftFailAgent(_OKAgent):
        def run(self, task):
            return AgentResult(False, "", [], "", None, 0.1, error="soft failure")

    chain = [_SoftFailAgent("codex"), _OKAgent("gemini")]
    result = _runner(chain, tmp_path).run(AgentTask(prompt="p", cwd=tmp_path))
    assert result.summary == "gemini ok"


def test_agent_not_installed_advances_chain(tmp_path):
    """Regression test for I-1. If a binary vanishes between healthcheck and run,
    AgentNotInstalledError must route to the next agent, not tear through."""
    from ai_agents.errors import AgentNotInstalledError

    class _MissingAgent(_OKAgent):
        def run(self, task):
            raise AgentNotInstalledError(
                f"{self.name} binary gone",
                context={"agent_name": self.name},
            )

    chain = [_MissingAgent("codex"), _OKAgent("gemini")]
    result = _runner(chain, tmp_path).run(AgentTask(prompt="p", cwd=tmp_path))
    assert result.summary == "gemini ok"
