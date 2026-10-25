"""Per-task + daily spend cap enforcement for paid AI agent calls.

Subscription-tier agents (cost_tier == 'free') bypass entirely. See spec section
`cost_guard.py`. State is persisted as JSON keyed by ISO date so the daily cap
rolls over at midnight local time.

This module is NOT thread-safe: state is a single JSON file with non-atomic reads. Relies on the single-task-at-a-time scheduler in the orchestration loop (README).
Setting `daily_cap_usd=0` is a valid configuration: every paid call fails `precheck` — effectively a kill-switch for paid backends (free-tier bypasses regardless).
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Protocol

from ai_agents.base import AgentResult
from ai_agents.errors import BudgetExceededError

_log = logging.getLogger("ai_agents.cost_guard")


class _AgentLike(Protocol):
    name: str
    cost_tier: str


def _today_iso() -> str:
    return date.today().isoformat()


class CostGuard:
    def __init__(
        self,
        per_task_cap_usd: float,
        daily_cap_usd: float,
        state_path: Path,
    ) -> None:
        self._per_task_cap = per_task_cap_usd
        self._daily_cap = daily_cap_usd
        self._state_path = state_path

    def precheck(self, agent: _AgentLike) -> None:
        """Raise BudgetExceededError if adding one more paid call would breach the daily cap."""
        if agent.cost_tier == "free":
            return
        spend = self._today_spend()
        if spend >= self._daily_cap:
            raise BudgetExceededError(
                f"Daily spend ${spend:.2f} >= cap ${self._daily_cap:.2f}",
                context={"agent_name": agent.name, "daily_spend": spend, "cap": self._daily_cap},
            )

    def record(self, result: AgentResult) -> None:
        """Persist this call's cost and raise if per-task cap was breached."""
        if result.cost_usd is None:
            return
        self._persist(result.cost_usd)
        if result.cost_usd > self._per_task_cap:
            raise BudgetExceededError(
                f"Per-task spend ${result.cost_usd:.2f} > cap ${self._per_task_cap:.2f}",
                context={"cost_usd": result.cost_usd, "cap": self._per_task_cap},
            )

    def _today_spend(self) -> float:
        data = self._load()
        return float(data.get(_today_iso(), 0.0))

    def _persist(self, cost_usd: float) -> None:
        data = self._load()
        today = _today_iso()
        data[today] = float(data.get(today, 0.0)) + float(cost_usd)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(self._state_path)       # atomic rename on POSIX; closes partial-write window
        _log.info("spend_recorded cost=%.4f today=%.4f", cost_usd, data[today])

    def _load(self) -> dict[str, float]:
        if not self._state_path.exists():
            return {}
        try:
            return json.loads(self._state_path.read_text())
        except (OSError, json.JSONDecodeError):
            _log.warning("Unreadable spend state at %s — resetting.", self._state_path)
            return {}
