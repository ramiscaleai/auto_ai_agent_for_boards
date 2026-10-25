"""E2E: real `gemini` CLI is installed and authenticated."""
from ai_agents import GeminiAgent


def test_gemini_healthcheck_passes():
    assert GeminiAgent().healthcheck() is True, "Run `gemini` interactively once to log in."
