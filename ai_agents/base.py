"""Provider-agnostic base types for the AI Agent layer.

See spec section `base.py` — every subclass implements `run`, `chat`, `healthcheck`.
Each CLI auto-reads its own convention file (AGENTS.md / GEMINI.md) from task.cwd
natively; this library does not author, inject, or fall back between them.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CostTier = Literal["free", "low", "medium", "high"]


@dataclass(frozen=True)
class AgentTask:
    """A single unit of work handed to AIAgent.run()."""

    prompt: str
    cwd: Path
    allowed_tools: frozenset[str] = frozenset({"read", "write", "bash"})
    timeout_s: int = 1800


@dataclass(frozen=True)
class AgentResult:
    """Outcome of an AIAgent.run() invocation."""

    success: bool
    summary: str
    files_changed: list[Path]
    output: str
    cost_usd: float | None
    duration_s: float
    error: str | None = None
    questions: list[str] | None = None


class AIAgent(ABC):
    """Base class for all coding-agent backends."""

    name: str
    cost_tier: CostTier

    @abstractmethod
    def run(self, task: AgentTask) -> AgentResult:
        """Execute the task by editing files under task.cwd. Provider-agnostic contract."""

    @abstractmethod
    def chat(self, prompt: str, timeout_s: int = 60) -> str:
        """Text-only call — no tool use, no file edits. Used by AgentStructuredLLM.

        Implementations run in an ephemeral tempdir so no convention file pollutes
        the non-code call.
        """

    @abstractmethod
    def healthcheck(self) -> bool:
        """Return True if the CLI is installed and authenticated. Called once per registry load."""
