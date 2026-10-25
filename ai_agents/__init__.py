"""AI Agent layer — provider-agnostic coding agent abstraction.

Public API:
    AIAgent, AgentTask, AgentResult        — core types
    CodexAgent, GeminiAgent, OpenCodeAgent — concrete subclasses
    AgentRegistry                          — YAML + .env loader, priority chains
    AgentRunner                            — coding fallback chain executor
    CostGuard                              — per-task + daily spend caps
    StructuredLLM, AgentStructuredLLM,
    LiteLLMStructuredLLM, ChainedStructuredLLM — non-code JSON LLM helpers
    make_tracer, NoOpTracer                — observability (Langfuse optional)
    AIAgentError + subclasses              — typed exceptions
"""
from ai_agents.base import AIAgent, AgentResult, AgentTask
from ai_agents.codex_agent import CodexAgent
from ai_agents.cost_guard import CostGuard
from ai_agents.errors import (
    AgentAuthError,
    AgentNotInstalledError,
    AgentTimeoutError,
    AgentToolError,
    AIAgentError,
    AllAgentsFailedError,
    BudgetExceededError,
    ConfigError,
    StructuredLLMParseError,
    redact_secrets,
)
from ai_agents.gemini_agent import GeminiAgent
from ai_agents.opencode_agent import OpenCodeAgent
from ai_agents.registry import AgentRegistry
from ai_agents.runner import AgentRunner
from ai_agents.structured_llm import (
    AgentStructuredLLM,
    ChainedStructuredLLM,
    LiteLLMStructuredLLM,
    StructuredLLM,
)
from ai_agents.tracing import NoOpTracer, Tracer, make_tracer

__all__ = [
    "AIAgent", "AgentTask", "AgentResult",
    "CodexAgent", "GeminiAgent", "OpenCodeAgent",
    "AgentRegistry", "AgentRunner", "CostGuard",
    "StructuredLLM", "AgentStructuredLLM", "LiteLLMStructuredLLM", "ChainedStructuredLLM",
    "Tracer", "NoOpTracer", "make_tracer",
    "AIAgentError", "AgentAuthError", "AgentNotInstalledError",
    "AgentTimeoutError", "AgentToolError", "AllAgentsFailedError",
    "BudgetExceededError", "ConfigError", "StructuredLLMParseError",
    "redact_secrets",
]
