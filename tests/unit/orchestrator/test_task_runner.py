from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from ai_agents.base import AgentResult
from boards.board import Comment, Task
from orchestrator.trello_resolver import ResolvedTrelloBoard
from orchestrator.task_runner import TaskRunner
from repo_identifier.models import RepoSelection

MODULE = "orchestrator.task_runner"

_TASK = Task(id="t1", name="Fix bug", description="desc", list_name="To Do", url="https://t.c/1")
_REPO_PATH = Path("/repo")


def _result(success=True, questions=None, summary="done", error=None):
    return AgentResult(
        success=success, summary=summary, files_changed=[],
        output="", cost_usd=None, duration_s=1.0, error=error, questions=questions,
    )


def _make(board=None, identifier=None, runner=None, to_review="To Review", waiting="Waiting for answers", agent_timeout_s=1800):
    board = board or MagicMock()
    identifier = identifier or MagicMock()
    identifier.identify_selection.return_value = RepoSelection(
        repos=(MagicMock(path=_REPO_PATH, name="backend"),),
        rationale="test rationale",
    )
    runner = runner or MagicMock()
    namer = MagicMock()
    namer.name.return_value = "task/fix-bug-t1ab"
    trello_resolver = MagicMock()
    trello_resolver.resolve.return_value = ResolvedTrelloBoard(
        board=board,
        to_do_list="To Do",
        to_review_list=to_review,
        waiting_list=waiting,
        source="test",
    )
    return TaskRunner(
        board=board, identifier=identifier, runner=runner,
        branch_namer=namer,
        to_review_list=to_review, waiting_list=waiting, agent_timeout_s=agent_timeout_s,
        trello_resolver=trello_resolver,
    )


@patch(f"{MODULE}.TaskWorkspace")
def test_success_moves_card(mock_ws):
    mock_ws.return_value.__enter__ = lambda s: s
    mock_ws.return_value.__exit__ = MagicMock(return_value=False)
    mock_ws.return_value.cwd = _REPO_PATH
    mock_ws.return_value.stage_and_commit = MagicMock(return_value=True)
    mock_ws.return_value.merge_main_in = MagicMock()
    mock_ws.return_value.merge_back_to_main = MagicMock()

    board = MagicMock()
    board.get_comments.return_value = []
    tr = _make(board=board)
    tr._runner.run.return_value = _result(success=True)

    outcome = tr.run(_TASK)

    assert outcome.status == "done"
    board.move_task.assert_called_once_with("t1", "To Review")
    board.add_comment.assert_called_once()


@patch(f"{MODULE}.TaskWorkspace")
def test_questions_returns_questions_status(mock_ws):
    mock_ws.return_value.__enter__ = lambda s: s
    mock_ws.return_value.__exit__ = MagicMock(return_value=False)
    mock_ws.return_value.cwd = _REPO_PATH
    mock_ws.return_value.stage_and_commit = MagicMock(return_value=False)

    board = MagicMock()
    board.get_comments.return_value = []
    tr = _make(board=board)
    tr._runner.run.return_value = _result(success=False, questions=["What DB to use?"])

    outcome = tr.run(_TASK)

    assert outcome.status == "questions"
    assert outcome.waiting_list == "Waiting for answers"
    board.move_task.assert_not_called()


@patch(f"{MODULE}.TaskWorkspace")
def test_agent_timeout_s_forwarded_to_agent_task(mock_ws):
    mock_ws.return_value.__enter__ = lambda s: s
    mock_ws.return_value.__exit__ = MagicMock(return_value=False)
    mock_ws.return_value.cwd = _REPO_PATH
    mock_ws.return_value.stage_and_commit = MagicMock(return_value=False)

    tr = _make(agent_timeout_s=900)
    tr._board.get_comments.return_value = []
    tr._runner.run.return_value = _result(success=True)
    tr.run(_TASK)

    called_task = tr._runner.run.call_args[0][0]
    assert called_task.timeout_s == 900


@patch(f"{MODULE}.TaskWorkspace")
def test_failure_adds_comment(mock_ws):
    mock_ws.return_value.__enter__ = lambda s: s
    mock_ws.return_value.__exit__ = MagicMock(return_value=False)
    mock_ws.return_value.cwd = _REPO_PATH
    mock_ws.return_value.stage_and_commit = MagicMock(return_value=False)

    board = MagicMock()
    board.get_comments.return_value = []
    tr = _make(board=board)
    tr._runner.run.return_value = _result(success=False, error="auth failed")

    outcome = tr.run(_TASK)

    assert outcome.status == "failed"
    board.add_comment.assert_called_once()
    board.move_task.assert_not_called()


@patch(f"{MODULE}.TaskWorkspace")
def test_success_uses_resolved_board_lists(mock_ws):
    mock_ws.return_value.__enter__ = lambda s: s
    mock_ws.return_value.__exit__ = MagicMock(return_value=False)
    mock_ws.return_value.cwd = _REPO_PATH
    mock_ws.return_value.stage_and_commit = MagicMock(return_value=True)
    mock_ws.return_value.merge_main_in = MagicMock()
    mock_ws.return_value.merge_back_to_main = MagicMock()

    default_board = MagicMock()
    default_board.get_comments.return_value = []
    resolved_board = MagicMock()
    resolved_board.get_comments.return_value = []
    tr = _make(board=default_board, to_review="Repo Review")
    tr._trello_resolver.resolve.return_value = ResolvedTrelloBoard(
        board=resolved_board,
        to_do_list="To Do",
        to_review_list="Repo Review",
        waiting_list="Repo Waiting",
        source="repos.md",
    )
    tr._runner.run.return_value = _result(success=True)

    outcome = tr.run(_TASK)

    assert outcome.status == "done"
    resolved_board.add_comment.assert_called_once_with("t1", "done")
    resolved_board.move_task.assert_called_once_with("t1", "Repo Review")
    default_board.move_task.assert_not_called()


@patch(f"{MODULE}.TaskWorkspace")
def test_prompt_includes_comments_and_repo_context(mock_ws):
    mock_ws.return_value.__enter__ = lambda s: s
    mock_ws.return_value.__exit__ = MagicMock(return_value=False)
    mock_ws.return_value.cwd = _REPO_PATH
    mock_ws.return_value.branch = "task/fix-bug-t1ab"
    mock_ws.return_value.stage_and_commit = MagicMock(return_value=False)
    mock_ws.return_value.merge_main_in = MagicMock()
    mock_ws.return_value.merge_back_to_main = MagicMock()

    board = MagicMock()
    board.get_comments.return_value = [
        Comment(
            id="c1",
            author="Alice",
            text="Please keep auth optional.",
            created_at=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc),
        )
    ]
    tr = _make(board=board)
    tr._runner.run.return_value = _result(success=True)

    tr.run(_TASK)

    prompt = tr._runner.run.call_args[0][0].prompt
    assert "Please keep auth optional." in prompt
    assert "Repo context:" in prompt
    assert "Routing rationale: test rationale" in prompt
    assert "Current branch: task/fix-bug-t1ab" in prompt
