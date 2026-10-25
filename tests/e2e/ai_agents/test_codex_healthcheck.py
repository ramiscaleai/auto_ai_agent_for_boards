"""E2E: real `codex` CLI is installed and authenticated."""
from ai_agents import CodexAgent


def test_codex_healthcheck_passes():
    assert CodexAgent().healthcheck() is True, "Run `codex login` if this fails."
