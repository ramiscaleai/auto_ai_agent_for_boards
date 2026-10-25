from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from boards.board import Task
from boards.repo_backlog_seeder import RepoBacklogSeeder, SeedOutcome
from orchestrator.task_runner import TaskRunner
from orchestrator.trello_resolver import ResolvedTrelloBoard
from repo_identifier.models import RepoEntry, RepoSelection


def _seed_task(name="add top 32 tasks to Backlog for shop-app", desc=None):
    return Task(
        id="seed1", name=name,
        description=desc or (
            "add to trello Backlog top 32 most relevant tasks include: "
            "at least 10 for backend and least 5 for frontend which is not trello."
        ),
        list_name="To Do", url="https://t.c/seed1",
    )


def _make_runner(*, seeder, seed_outcome):
    board = MagicMock()
    resolved = ResolvedTrelloBoard(
        board=board, to_do_list="To Do", to_review_list="To Review",
        waiting_list="Waiting for answers", backlog_list="Backlog", source="test",
    )
    resolver = MagicMock(); resolver.resolve.return_value = resolved
    repo = RepoEntry(
        name="shop-app", path=Path("/tmp/shop-app"),
        description="Online shop", tags=(), trello_board_id="b1",
    )
    identifier = MagicMock()
    identifier.identify_selection.return_value = RepoSelection(
        repos=(repo,), rationale="only repo matching",
    )
    agent_runner = MagicMock()
    branch_namer = MagicMock()
    seeder.seed.return_value = seed_outcome
    tr = TaskRunner(
        board=board, identifier=identifier, runner=agent_runner,
        branch_namer=branch_namer, to_review_list="To Review",
        waiting_list="Waiting for answers", trello_resolver=resolver,
        backlog_seeder=seeder,
    )
    return tr, board, agent_runner, branch_namer, seeder, repo


class TestTaskRunnerSeedRouting:
    def test_seed_intent_bypasses_agent_runner(self):
        seeder = MagicMock(spec=RepoBacklogSeeder)
        outcome = SeedOutcome(
            requested=32,
            created=tuple(f"[Backend] t{i}" for i in range(32)),
            skipped_existing=(),
        )
        tr, board, agent_runner, branch_namer, seeder, repo = _make_runner(
            seeder=seeder, seed_outcome=outcome,
        )

        result = tr.run(_seed_task())

        assert result.status == "done"
        agent_runner.run.assert_not_called()
        branch_namer.name.assert_not_called()
        seeder.seed.assert_called_once()
        call_kwargs = seeder.seed.call_args
        assert call_kwargs.args[0] == repo
        assert call_kwargs.args[1].count == 32
        board.move_task.assert_called_once_with("seed1", "To Review")
        board.add_comment.assert_called_once()
        comment_text = board.add_comment.call_args.args[1]
        assert "32" in comment_text and "Backlog" in comment_text

    def test_seed_short_delta_marks_task_failed(self):
        seeder = MagicMock(spec=RepoBacklogSeeder)
        outcome = SeedOutcome(
            requested=32,
            created=tuple(f"[Backend] t{i}" for i in range(12)),
            skipped_existing=(),
            reason="LLM only produced 12 tasks after retries",
        )
        tr, board, *_ = _make_runner(seeder=seeder, seed_outcome=outcome)

        result = tr.run(_seed_task())

        assert result.status == "failed"
        board.move_task.assert_not_called()
        board.add_comment.assert_called_once()

    def test_non_seed_card_routes_to_agent_runner(self, monkeypatch):
        """A regular coding card must NOT hit the seeder path."""
        import orchestrator.task_runner as tr_mod
        monkeypatch.setattr(tr_mod, "TaskWorkspace", MagicMock())

        seeder = MagicMock(spec=RepoBacklogSeeder)
        tr, board, agent_runner, branch_namer, *_ = _make_runner(
            seeder=seeder,
            seed_outcome=SeedOutcome(requested=0, created=(), skipped_existing=()),
        )
        board.get_comments.return_value = []
        agent_runner.run.return_value = MagicMock(
            success=True, summary="ok", files_changed=[], output="", cost_usd=None,
            duration_s=1.0, error=None, questions=None,
        )

        tr.run(Task(id="c1", name="Fix login bug", description="null pointer",
                    list_name="To Do", url="https://t.c/c1"))

        seeder.seed.assert_not_called()
        agent_runner.run.assert_called_once()
