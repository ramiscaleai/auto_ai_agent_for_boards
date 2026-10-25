"""Unit tests for ai_agents/errors.py — spec section `errors.py`."""
from ai_agents.errors import (
    AIAgentError,
    AgentAuthError,
    AgentNotInstalledError,
    AgentTimeoutError,
    AgentToolError,
    AllAgentsFailedError,
    BudgetExceededError,
    ConfigError,
    StructuredLLMParseError,
    redact_secrets,
)


def test_all_errors_inherit_from_aiagenterror():
    for cls in (
        ConfigError,
        AgentNotInstalledError,
        AgentAuthError,
        AgentToolError,
        AgentTimeoutError,
        BudgetExceededError,
        StructuredLLMParseError,
        AllAgentsFailedError,
    ):
        assert issubclass(cls, AIAgentError), cls


def test_aiagenterror_inherits_from_runtimeerror():
    assert issubclass(AIAgentError, RuntimeError)


def test_exception_carries_context():
    err = AgentToolError("boom", context={"agent_name": "codex", "task_id": "t1"})
    assert err.context == {"agent_name": "codex", "task_id": "t1"}
    assert "boom" in str(err)


def test_exception_context_defaults_to_empty_dict():
    err = AgentAuthError("unauthorized")
    assert err.context == {}


def test_redact_secrets_masks_api_key_values():
    env = {"ANTHROPIC_API_KEY": "sk-abc123", "OPENROUTER_API_KEY": "or-xyz456", "FOO": "bar"}
    message = "Failed with sk-abc123 and or-xyz456; FOO=bar"
    masked = redact_secrets(message, env)
    assert "sk-abc123" not in masked
    assert "or-xyz456" not in masked
    assert "bar" in masked  # FOO does not match *_API_KEY / *_TOKEN / *_SECRET


def test_redact_secrets_masks_token_and_secret_keys():
    env = {"TRELLO_TOKEN": "tok-1", "TRELLO_SECRET": "sec-2"}
    message = "token=tok-1 secret=sec-2"
    masked = redact_secrets(message, env)
    assert "tok-1" not in masked
    assert "sec-2" not in masked


def test_redact_secrets_ignores_empty_values():
    env = {"ANTHROPIC_API_KEY": ""}
    message = "Message with no secret present"
    assert redact_secrets(message, env) == message


def test_context_string_values_are_redacted(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-leak-xyz")
    err = AgentToolError("boom", context={"cmd": "run --key sk-leak-xyz", "duration": 5})
    assert "sk-leak-xyz" not in err.context["cmd"]
    assert "***" in err.context["cmd"]
    assert err.context["duration"] == 5  # non-strings pass through


def test_redact_secrets_prefers_longest_match(monkeypatch):
    env = {"A_API_KEY": "abc", "B_API_KEY": "abc123"}
    msg = "both here: abc123"
    out = redact_secrets(msg, env)
    # Longer secret masked first; shorter must not corrupt what's left.
    assert "abc123" not in out
    assert out.count("***") == 1
