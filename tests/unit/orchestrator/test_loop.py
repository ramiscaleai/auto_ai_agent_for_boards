from unittest.mock import MagicMock, patch

from boards.board import Task
from orchestrator.loop import OrchestratorLoop
from orchestrator.task_runner import TaskOutcome

_TASK = Task(id="t1", name="Fix bug", description="desc", list_name="To Do", url="https://t.c/1")


def _loop(tasks=None):
    board = MagicMock()
    board.list_tasks.return_value = tasks or []
    task_runner = MagicMock()
    task_runner.run.return_value = MagicMock(status="done")
    return OrchestratorLoop(board=board, task_runner=task_runner, to_do_list="To Do", poll_interval_s=1)


def test_run_once_no_tasks_returns_false():
    loop = _loop(tasks=[])
    assert loop.run_once() is False


def test_run_once_with_task_returns_true():
    loop = _loop(tasks=[_TASK])
    assert loop.run_once() is True
    loop._task_runner.run.assert_called_once_with(_TASK)


def test_run_once_picks_first_task():
    task_a = Task(id="a", name="A", description="", list_name="To Do", url="")
    task_b = Task(id="b", name="B", description="", list_name="To Do", url="")
    loop = _loop(tasks=[task_a, task_b])
    loop.run_once()
    loop._task_runner.run.assert_called_once_with(task_a)


@patch("orchestrator.loop.time.sleep")
def test_run_forever_stops_on_keyboard_interrupt(mock_sleep):
    loop = _loop(tasks=[_TASK])
    mock_sleep.side_effect = KeyboardInterrupt
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    loop._task_runner.run.assert_called()


@patch("orchestrator.loop.time.sleep")
def test_run_forever_catches_exceptions(mock_sleep):
    call_count = 0

    def boom(*a, **k):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise KeyboardInterrupt
        raise RuntimeError("boom")

    loop = _loop(tasks=[_TASK])
    loop._task_runner.run.side_effect = boom
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    assert call_count >= 1
