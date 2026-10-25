"""Deterministic backlog seeder — generates N task templates for a specific
repo via StructuredLLM, writes them directly to the board.

Bypasses the coding-agent layer so it works even when the target repo has no
Trello credentials and no trello_cli.py (fixes the d0ox8iG8 fake-done class).

Generation is LLM-assisted but card creation is deterministic: create_task()
is called straight on the Board. Retries on constraint violation rather than
fabricating or relaxing the constraints.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from ai_agents.structured_llm import StructuredLLM
from boards.backlog_seed_intent import SeedIntent
from boards.board import Board
from repo_identifier.models import RepoEntry

_log = logging.getLogger(__name__)

Area = Literal["Backend", "Frontend", "DevEx", "Research", "Infra"]


class GeneratedTask(BaseModel):
    title: str = Field(..., min_length=8, max_length=120)
    area: Area
    impact: str = Field(..., min_length=20, max_length=500)
    repo_fit: str = Field(..., min_length=20, max_length=500)
    acceptance_criteria: list[str] = Field(..., min_length=2, max_length=6)


class GeneratedBacklog(BaseModel):
    tasks: list[GeneratedTask]


@dataclass(frozen=True)
class SeedOutcome:
    requested: int
    created: tuple[str, ...]
    skipped_existing: tuple[str, ...]
    reason: str | None = None

    @property
    def success(self) -> bool:
        return self.reason is None and len(self.created) + len(self.skipped_existing) >= self.requested

    def summary(self) -> str:
        base = (
            f"Seed result: requested={self.requested} "
            f"created={len(self.created)} skipped_existing={len(self.skipped_existing)}"
        )
        return f"{base} reason={self.reason}" if self.reason else base


class RepoBacklogSeeder:
    def __init__(
        self,
        llm: StructuredLLM,
        max_generation_retries: int = 2,
        chat_timeout_s: int = 300,
    ) -> None:
        self._llm = llm
        self._max_retries = max_generation_retries
        self._chat_timeout_s = chat_timeout_s

    def seed(
        self,
        repo: RepoEntry,
        intent: SeedIntent,
        board: Board,
        backlog_list: str,
    ) -> SeedOutcome:
        _log.info(
            "Seeding backlog for repo=%s count=%d min_backend=%d min_frontend=%d list=%s",
            repo.name, intent.count, intent.min_backend, intent.min_frontend, backlog_list,
        )
        existing = {task.name for task in board.list_tasks(backlog_list)}
        try:
            generated = self._generate_valid(repo, intent, existing_names=existing)
        except ValueError as exc:
            return SeedOutcome(requested=intent.count, created=(), skipped_existing=(), reason=str(exc))

        created: list[str] = []
        skipped: list[str] = []
        for task in generated.tasks[: intent.count]:
            card_name = _card_name(task)
            if card_name in existing:
                skipped.append(card_name)
                continue
            board.create_task(backlog_list, card_name, _card_description(task, repo))
            existing.add(card_name)
            created.append(card_name)
        return SeedOutcome(
            requested=intent.count,
            created=tuple(created),
            skipped_existing=tuple(skipped),
        )

    def _generate_valid(
        self, repo: RepoEntry, intent: SeedIntent, existing_names: set[str],
    ) -> GeneratedBacklog:
        feedback: str | None = None
        for attempt in range(self._max_retries + 1):
            prompt = _build_prompt(repo, intent, existing_names, feedback)
            result = self._llm.ask(
                prompt, GeneratedBacklog, max_retries=1, chat_timeout_s=self._chat_timeout_s,
            )
            try:
                _validate(result, intent, existing_names)
                return result
            except ValueError as exc:
                feedback = str(exc)
                _log.warning("Generation attempt %d rejected: %s", attempt + 1, feedback)
        raise ValueError(f"Backlog generation failed after {self._max_retries + 1} attempts: {feedback}")


def _validate(backlog: GeneratedBacklog, intent: SeedIntent, existing_names: set[str]) -> None:
    if len(backlog.tasks) < intent.count:
        raise ValueError(f"Need {intent.count} tasks, got {len(backlog.tasks)}")
    names = [_card_name(t) for t in backlog.tasks[: intent.count]]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate card titles produced")
    new_names = [n for n in names if n not in existing_names]
    if len(new_names) < (intent.count - len(existing_names & set(names))):
        raise ValueError("Too many titles collide with existing Backlog cards — please propose fresh items")
    tasks = backlog.tasks[: intent.count]
    backend = sum(t.area == "Backend" for t in tasks)
    frontend = sum(t.area == "Frontend" for t in tasks)
    if backend < intent.min_backend:
        raise ValueError(f"Need at least {intent.min_backend} Backend tasks, got {backend}")
    if frontend < intent.min_frontend:
        raise ValueError(f"Need at least {intent.min_frontend} Frontend tasks, got {frontend}")
    if intent.frontend_excludes_trello:
        fe_trello = [t.title for t in tasks if t.area == "Frontend" and "trello" in t.title.lower()]
        if fe_trello:
            raise ValueError(f"Frontend tasks must not target Trello UI; violators: {fe_trello}")


def _build_prompt(
    repo: RepoEntry, intent: SeedIntent, existing_names: set[str], feedback: str | None,
) -> str:
    existing_block = "\n".join(f"- {n}" for n in sorted(existing_names)[:60]) or "(none)"
    feedback_block = f"\nFeedback on previous attempt: {feedback}\nFix the feedback and try again.\n" if feedback else ""
    fe_rule = (
        "- At least {n} Frontend tasks that do NOT target Trello UI (build our own UI in this repo).\n"
        if intent.frontend_excludes_trello else
        "- At least {n} Frontend tasks.\n"
    ).format(n=intent.min_frontend)
    return (
        "You are scoping a product backlog for one specific repository.\n\n"
        f"Repository: {repo.name}\n"
        f"Path: {repo.path}\n"
        f"Description: {repo.description}\n"
        f"Tags: {', '.join(repo.tags) if repo.tags else '(none)'}\n\n"
        f"Goal: produce exactly {intent.count} distinct, high-impact tasks for this repository's Trello Backlog.\n"
        "Constraints:\n"
        f"- At least {intent.min_backend} Backend tasks.\n"
        f"{fe_rule}"
        "- Each task must be implementable and scoped to this repository (not cross-repo infra).\n"
        "- Each title must be unique, short, imperative, and describe the outcome.\n"
        "- Include research-informed ideas from similar public products, but do not copy branded phrasing.\n"
        "- area must be one of: Backend, Frontend, DevEx, Research, Infra.\n"
        "- acceptance_criteria: 2-5 short bullets that would let a reviewer verify completion.\n\n"
        "Existing Backlog titles to avoid duplicating:\n"
        f"{existing_block}\n"
        f"{feedback_block}"
        f'Return JSON matching the GeneratedBacklog schema with "tasks" containing exactly {intent.count} entries.'
    )


def _card_name(task: GeneratedTask) -> str:
    return f"[{task.area}] {task.title.strip()}"


def _card_description(task: GeneratedTask, repo: RepoEntry) -> str:
    criteria = "\n".join(f"- {c}" for c in task.acceptance_criteria)
    return (
        f"Repo: {repo.name}  ({repo.path})\n\n"
        f"Impact\n{task.impact}\n\n"
        f"Why this repo\n{task.repo_fit}\n\n"
        f"Acceptance criteria\n{criteria}"
    )
