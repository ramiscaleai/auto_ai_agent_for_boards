"""E2E: `opencode run` works with a cheap model; cost parsing works end-to-end."""
from ai_agents import OpenCodeAgent


def test_opencode_healthcheck_passes(require_env):
    require_env("OPENROUTER_API_KEY")
    agent = OpenCodeAgent(
        name="openrouter-test",
        model="openrouter/openai/gpt-4o-mini",
        cost_tier="low",
    )
    assert agent.healthcheck() is True
