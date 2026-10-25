"""Tests for stuck-handler and auto-answerer wiring in OrchestratorLoop."""
from unittest.mock import MagicMock, patch

from boards.board import Task
from orchestrator.loop import OrchestratorLoop

_TASK = Task(id="t1", name="Fix bug", description="desc", list_name="To Do", url="")


def _loop(tasks=None, outcome_status="questions", questions=None, stuck=None, answerer=None):
    board = MagicMock()
    board.list_tasks.return_value = tasks if tasks is not None else [_TASK]
    task_runner = MagicMock()
    result = MagicMock()
    result.questions = questions
    task_runner.run.return_value = MagicMock(
        status=outcome_status,
        result=result,
        resolved_task=_TASK,
        resolved_board=board,
        waiting_list="Waiting",
    )
    return OrchestratorLoop(
        board=board,
        task_runner=task_runner,
        to_do_list="To Do",
        poll_interval_s=1,
        stuck_handler=stuck,
        auto_answerer=answerer,
    )


def test_stuck_handler_called_on_questions():
    stuck = MagicMock()
    loop = _loop(outcome_status="questions", questions=["Q1"], stuck=stuck)
    loop.run_once()
    stuck.handle.assert_called_once_with(_TASK, ["Q1"], board=loop._board, waiting_list="Waiting")


def test_stuck_handler_not_called_on_done():
    stuck = MagicMock()
    loop = _loop(outcome_status="done", questions=None, stuck=stuck)
    loop.run_once()
    stuck.handle.assert_not_called()


def test_stuck_handler_not_called_when_none():
    loop = _loop(outcome_status="questions", questions=["Q1"], stuck=None)
    loop.run_once()  # should not raise


def test_auto_answerer_called_each_tick():
    answerer = MagicMock()
    loop = _loop(answerer=answerer)
    loop.run_once()
    answerer.check_and_answer.assert_called_once()


def test_auto_answerer_called_even_when_no_tasks():
    answerer = MagicMock()
    loop = _loop(tasks=[], answerer=answerer)
    loop.run_once()
    answerer.check_and_answer.assert_called_once()
