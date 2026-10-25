from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from boards.backlog_seed_intent import SeedIntent
from boards.board import Board, Task
from boards.repo_backlog_seeder import (
    GeneratedBacklog,
    GeneratedTask,
    RepoBacklogSeeder,
)
from repo_identifier.models import RepoEntry


class FakeBoard(Board):
    def __init__(self) -> None:
        self.cards_by_list: dict[str, list[Task]] = {}
        self.created: list[tuple[str, str, str]] = []

    def get_lists(self): return list(self.cards_by_list)

    def list_tasks(self, list_name: str):
        return list(self.cards_by_list.get(list_name, []))

    def create_task(self, list_name: str, name: str, description: str = "") -> Task:
        task = Task(id=f"id-{len(self.created)}", name=name, description=description,
                    list_name=list_name, url=f"https://example/{name}")
        self.cards_by_list.setdefault(list_name, []).append(task)
        self.created.append((list_name, name, description))
        return task

    def move_task(self, task_id, target_list_name): raise NotImplementedError
    def add_comment(self, task_id, text): raise NotImplementedError
    def get_comments(self, task_id): raise NotImplementedError
    def get_list_entry_time(self, task_id): return datetime.now(timezone.utc)


class ScriptedLLM:
    """Returns pre-built GeneratedBacklog objects on each `ask`."""

    def __init__(self, responses: list[GeneratedBacklog]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    def ask(self, prompt: str, schema, max_retries: int = 2, chat_timeout_s: int | None = None):
        self.calls.append(prompt)
        if not self._responses:
            raise AssertionError("No scripted responses left")
        return self._responses.pop(0)


def _gen_task(title: str, area: str = "Backend") -> GeneratedTask:
    return GeneratedTask(
        title=title,
        area=area,
        impact="This improves correctness, reliability, and observability for operators.",
        repo_fit="Fits because the repo already has the scaffolding described here.",
        acceptance_criteria=["covered by tests", "documented in README"],
    )


def _repo() -> RepoEntry:
    return RepoEntry(
        name="shop-app", path=Path("/tmp/shop-app"),
        description="Online shop with a REST API", tags=("python",),
        trello_board_id="boardX",
    )


def _intent(count=5, min_backend=3, min_frontend=2, excl_trello=True) -> SeedIntent:
    return SeedIntent(
        count=count, min_backend=min_backend, min_frontend=min_frontend,
        frontend_excludes_trello=excl_trello, raw_text=f"add top {count} tasks to Backlog",
    )


class TestRepoBacklogSeeder:
    def test_seeds_all_requested_cards_on_happy_path(self):
        tasks = [_gen_task(f"Backend feature {i}", "Backend") for i in range(3)] + \
                [_gen_task(f"Frontend feature {i}", "Frontend") for i in range(2)]
        llm = ScriptedLLM([GeneratedBacklog(tasks=tasks)])
        board = FakeBoard()
        seeder = RepoBacklogSeeder(llm=llm)
        outcome = seeder.seed(_repo(), _intent(), board, "Backlog")

        assert outcome.success is True
        assert len(outcome.created) == 5
        assert len(board.cards_by_list["Backlog"]) == 5
        assert outcome.reason is None

    def test_caps_created_cards_at_requested_count(self):
        """LLM may over-produce on retry; seeder must slice to intent.count."""
        tasks = (
            [_gen_task(f"Backend item {i}", "Backend") for i in range(3)]
            + [_gen_task(f"Frontend item {i}", "Frontend") for i in range(2)]
            + [_gen_task(f"Extra item {i}", "Backend") for i in range(5)]
        )
        llm = ScriptedLLM([GeneratedBacklog(tasks=tasks)])
        board = FakeBoard()
        seeder = RepoBacklogSeeder(llm=llm)
        outcome = seeder.seed(_repo(), _intent(count=5), board, "Backlog")
        assert len(outcome.created) == 5
        assert len(board.cards_by_list["Backlog"]) == 5

    def test_skips_existing_titles_idempotently(self):
        tasks = [_gen_task(f"Backend feature {i}", "Backend") for i in range(3)] + \
                [_gen_task(f"Frontend feature {i}", "Frontend") for i in range(2)]
        llm = ScriptedLLM([GeneratedBacklog(tasks=tasks)])
        board = FakeBoard()
        board.create_task("Backlog", "[Backend] Backend feature 0", "preexisting")

        seeder = RepoBacklogSeeder(llm=llm)
        outcome = seeder.seed(_repo(), _intent(), board, "Backlog")

        assert outcome.success is True
        assert len(outcome.created) == 4
        assert len(outcome.skipped_existing) == 1
        assert len(board.cards_by_list["Backlog"]) == 5

    def test_retries_when_area_constraints_violated(self):
        bad = GeneratedBacklog(tasks=[_gen_task(f"backend only item {i}", "Backend") for i in range(5)])
        good = GeneratedBacklog(tasks=[
            _gen_task("Backend A", "Backend"), _gen_task("Backend B", "Backend"),
            _gen_task("Backend C", "Backend"),
            _gen_task("Frontend A", "Frontend"), _gen_task("Frontend B", "Frontend"),
        ])
        llm = ScriptedLLM([bad, good])
        seeder = RepoBacklogSeeder(llm=llm)
        outcome = seeder.seed(_repo(), _intent(), FakeBoard(), "Backlog")
        assert outcome.success is True
        assert len(llm.calls) == 2
        assert "feedback" in llm.calls[1].lower()

    def test_fails_when_frontend_title_targets_trello_ui(self):
        tasks = [_gen_task(f"Backend topic {i}", "Backend") for i in range(3)] + [
            _gen_task("Redesign Trello board widgets", "Frontend"),
            _gen_task("Clean frontend dashboard", "Frontend"),
        ]
        bad = GeneratedBacklog(tasks=tasks)
        llm = ScriptedLLM([bad, bad, bad])
        seeder = RepoBacklogSeeder(llm=llm, max_generation_retries=1)
        outcome = seeder.seed(_repo(), _intent(), FakeBoard(), "Backlog")
        assert outcome.success is False
        assert "trello" in (outcome.reason or "").lower()

    def test_allows_frontend_body_that_only_compares_to_trello(self):
        """Body may mention Trello (e.g. 'unlike Trello'); only title drives the block."""
        compare_task = GeneratedTask(
            title="Build Creator Workspace Home",
            area="Frontend",
            impact="Standalone workspace with Trello-like kanban columns but owned by this app.",
            repo_fit="The repo has no UI yet; this gives creators a Trello-inspired home screen.",
            acceptance_criteria=["renders list columns", "supports drag"],
        )
        tasks = [_gen_task(f"Backend topic {i}", "Backend") for i in range(3)] + [
            compare_task,
            _gen_task("Asset Review Queue interface", "Frontend"),
        ]
        llm = ScriptedLLM([GeneratedBacklog(tasks=tasks)])
        seeder = RepoBacklogSeeder(llm=llm)
        outcome = seeder.seed(_repo(), _intent(), FakeBoard(), "Backlog")
        assert outcome.success is True

    def test_fails_if_llm_returns_too_few_tasks(self):
        llm = ScriptedLLM([GeneratedBacklog(tasks=[_gen_task("only one short task", "Backend")])] * 3)
        seeder = RepoBacklogSeeder(llm=llm, max_generation_retries=1)
        outcome = seeder.seed(_repo(), _intent(count=5), FakeBoard(), "Backlog")
        assert outcome.success is False
        assert "Need 5" in (outcome.reason or "") or "got 1" in (outcome.reason or "")

    def test_generation_prompt_includes_existing_titles(self):
        tasks = [_gen_task(f"new backend item {i}", "Backend") for i in range(3)] + \
                [_gen_task(f"new frontend item {i}", "Frontend") for i in range(2)]
        llm = ScriptedLLM([GeneratedBacklog(tasks=tasks)])
        board = FakeBoard()
        board.create_task("Backlog", "[Backend] Previously shipped work", "old")
        seeder = RepoBacklogSeeder(llm=llm)
        seeder.seed(_repo(), _intent(), board, "Backlog")
        assert "Previously shipped work" in llm.calls[0]
