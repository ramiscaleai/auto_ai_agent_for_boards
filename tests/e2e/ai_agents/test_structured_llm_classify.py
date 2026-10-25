"""E2E: StructuredLLM returns a valid Pydantic model using the first free agent."""
from pathlib import Path

from pydantic import BaseModel

from ai_agents import AgentRegistry


class Decision(BaseModel):
    is_coding_task: bool
    confidence: float


def test_structured_llm_classifies_tasks():
    yaml_path = Path(__file__).resolve().parents[3] / "config" / "agents.yml"
    registry = AgentRegistry.load(yaml_path, env={})
    sllm = registry.build_structured_llm()
    out = sllm.ask(
        "Is the task 'rename all variables in foo.py to camelCase' a coding task?",
        Decision,
    )
    assert isinstance(out, Decision)
    assert out.is_coding_task is True
    assert 0.0 <= out.confidence <= 1.0
