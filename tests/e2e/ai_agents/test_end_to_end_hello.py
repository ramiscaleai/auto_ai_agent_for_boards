"""E2E: AgentRunner produces hello.py in a tempdir using the first healthy agent."""
from pathlib import Path

import pytest
import yaml

from ai_agents import AgentRegistry, AgentRunner, AgentTask, CostGuard, NoOpTracer

PROMPT = 'Create a Python file named hello.py with exactly: print("hi")'


def test_runner_creates_hello_py(tmp_path, require_env):
    yaml_path = Path(__file__).resolve().parents[3] / "config" / "agents.yml"
    registry = AgentRegistry.load(yaml_path, env={})
    guard = CostGuard(per_task_cap_usd=0.10, daily_cap_usd=0.50, state_path=tmp_path / "s.json")
    runner = AgentRunner(registry=registry, cost_guard=guard, tracer=NoOpTracer())

    import subprocess
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)

    result = runner.run(AgentTask(prompt=PROMPT, cwd=tmp_path, timeout_s=180))

    assert result.success, f"run failed: {result.error}"
    hello = tmp_path / "hello.py"
    assert hello.exists(), "hello.py was not created"
    assert 'print("hi")' in hello.read_text()
    assert (result.cost_usd or 0.0) <= 0.10, f"cost {result.cost_usd} exceeded budget"
