"""AgentRunner — walks the coding chain, applies CostGuard, emits Tracer spans.

See spec section `runner.py`. Fails through on AgentAuthError/AgentToolError/
AgentTimeoutError; short-circuits on BudgetExceededError.
"""
from __future__ import annotations

import logging
import uuid
from typing import Protocol

from ai_agents.base import AgentResult, AgentTask, AIAgent
from ai_agents.cost_guard import CostGuard
from ai_agents.errors import (
    AgentAuthError,
    AgentNotInstalledError,
    AgentTimeoutError,
    AgentToolError,
    AllAgentsFailedError,
    BudgetExceededError,
)
from ai_agents.tracing import Tracer

_log = logging.getLogger("ai_agents.runner")


class _RegistryLike(Protocol):
    def coding_chain(self) -> list[AIAgent]: ...


class AgentRunner:
    def __init__(self, registry: _RegistryLike, cost_guard: CostGuard, tracer: Tracer) -> None:
        self._registry = registry
        self._cost_guard = cost_guard
        self._tracer = tracer

    def run(self, task: AgentTask) -> AgentResult:
        task_id = uuid.uuid4().hex[:12]
        attempted: list[str] = []
        errors: list[str] = []
        for agent in self._registry.coding_chain():
            attempted.append(agent.name)
            self._cost_guard.precheck(agent)  # BudgetExceededError propagates
            result = self._try_agent(agent, task, task_id, errors)
            if result is not None:
                return result
        raise AllAgentsFailedError(
            f"All {len(attempted)} agents failed for task {task_id}",
            context={"task_id": task_id, "attempted": attempted, "errors": errors},
        )

    def _try_agent(
        self, agent: AIAgent, task: AgentTask, task_id: str, errors: list[str],
    ) -> AgentResult | None:
        """Run one agent; return its result on success, None to signal 'try next'."""
        with self._tracer.span("agent.run", {"agent": agent.name, "task_id": task_id}):
            try:
                result = agent.run(task)
                self._cost_guard.record(result)
                if result.success:
                    _log.info(
                        "agent_success task_id=%s agent=%s duration=%.2f cost=%s",
                        task_id, agent.name, result.duration_s, result.cost_usd,
                    )
                    return result
                errors.append(f"{agent.name}: {result.error or 'success=False'}")
            except (AgentAuthError, AgentNotInstalledError, AgentToolError, AgentTimeoutError) as exc:
                _log.warning("agent_failed task_id=%s agent=%s err=%s", task_id, agent.name, exc)
                errors.append(f"{agent.name}: {exc}")
        return None
