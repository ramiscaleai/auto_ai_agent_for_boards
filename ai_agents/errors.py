"""Typed exceptions for the AI Agent layer.

Every raise site should populate `context` with `task_id`, `agent_name`,
redacted `cmd`, and the last 500 chars of `stdout_tail` so post-mortems
are one grep away. See spec section `errors.py`.

The base class auto-redacts both the message and string values in context
against os.environ, so a missed `redact_secrets` call at a log site won't
leak secrets stored on the exception.
"""
from __future__ import annotations

import os
import re
from typing import Any, Mapping

_SECRET_KEY_PATTERN = re.compile(r".*(?:_API_KEY|_TOKEN|_SECRET)$")


def redact_secrets(message: str, env: Mapping[str, str]) -> str:
    """Replace any value of *_API_KEY / *_TOKEN / *_SECRET env vars with `***`.

    Values are replaced longest-first so a short secret that's a substring of
    a longer one doesn't leave a partial leak. Empty values are skipped.
    """
    secrets = [
        v for k, v in env.items()
        if v and _SECRET_KEY_PATTERN.match(k)
    ]
    secrets.sort(key=len, reverse=True)
    redacted = message
    for value in secrets:
        redacted = redacted.replace(value, "***")
    return redacted


def _redact_context(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ctx with string values redacted; non-strings passed through."""
    return {
        k: (redact_secrets(v, os.environ) if isinstance(v, str) else v)
        for k, v in ctx.items()
    }


class AIAgentError(RuntimeError):
    """Base for all ai_agents/ exceptions."""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        super().__init__(redact_secrets(message, os.environ))
        self.context: dict[str, Any] = _redact_context(context) if context else {}


class ConfigError(AIAgentError):
    """agents.yml missing required keys, unknown agent name, etc."""


class AgentNotInstalledError(AIAgentError):
    """Healthcheck found the CLI binary missing or uninvokable."""


class AgentAuthError(AIAgentError):
    """CLI returned 401/403 or an auth-specific error."""


class AgentToolError(AIAgentError):
    """CLI returned non-zero exit for a non-auth reason."""


class AgentTimeoutError(AIAgentError):
    """CLI subprocess hit timeout_s."""


class BudgetExceededError(AIAgentError):
    """Per-task or daily spend cap reached — NOT recoverable by trying the next agent."""


class StructuredLLMParseError(AIAgentError):
    """JSON parse/validation failed after all retries in AgentStructuredLLM."""


class AllAgentsFailedError(AIAgentError):
    """Every agent in the fallback chain errored; see context['attempted']."""
