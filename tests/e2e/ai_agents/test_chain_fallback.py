"""E2E: primary forced to fail; next agent succeeds; both attempts logged."""
from pathlib import Path

from ai_agents import (
    AgentRegistry,
    AgentRunner,
    AgentTask,
    CodexAgent,
    CostGuard,
    NoOpTracer,
)
from ai_agents.errors import AgentToolError


class _AlwaysFailCodex(CodexAgent):
    def run(self, task):
        raise AgentToolError("forced failure for e2e fallback test", context={"agent_name": "codex"})


def test_primary_fails_second_succeeds(tmp_path, caplog):
    yaml_path = Path(__file__).resolve().parents[3] / "config" / "agents.yml"
    registry = AgentRegistry.load(yaml_path, env={})
    registry._agents["codex"] = _AlwaysFailCodex()  # type: ignore[attr-defined]

    guard = CostGuard(per_task_cap_usd=0.10, daily_cap_usd=0.50, state_path=tmp_path / "s.json")
    runner = AgentRunner(registry=registry, cost_guard=guard, tracer=NoOpTracer())

    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    with caplog.at_level("WARNING"):
        result = runner.run(AgentTask(
            prompt='Create a Python file named hi.py with exactly: print("hi")',
            cwd=tmp_path,
            timeout_s=180,
        ))
    assert result.success, f"fallback failed: {result.error}"
    assert any("codex" in r.message for r in caplog.records), "codex attempt should be logged"
