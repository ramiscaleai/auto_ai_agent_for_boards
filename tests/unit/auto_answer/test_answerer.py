from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from auto_answer.answerer import AutoAnswerer, AutoAnswers
from auto_answer.stuck_handler import _PREFIX
from boards.board import Comment, Task

_TASK = Task(id="t1", name="Fix auth", description="desc", list_name="Waiting", url="")

_OLD_TIME = datetime.now(timezone.utc) - timedelta(hours=72)
_NEW_TIME = datetime.now(timezone.utc) - timedelta(hours=1)


def _comment(text: str, hours_ago: int = 50) -> Comment:
    return Comment(
        id="c1",
        author="AI Agent",
        text=text,
        created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )


def _make(board=None, hours=48) -> AutoAnswerer:
    board = board or MagicMock()
    llm = MagicMock()
    llm.ask.return_value = AutoAnswers(answers="Use PostgreSQL on port 5432.")
    return AutoAnswerer(board=board, waiting_list="Waiting", to_do_list="To Do", auto_answer_hours=hours, llm=llm)


def test_overdue_card_is_answered():
    board = MagicMock()
    board.list_tasks.return_value = [_TASK]
    board.get_list_entry_time.return_value = _OLD_TIME
    board.get_comments.return_value = [_comment(f"{_PREFIX}1. What DB?")]

    aa = _make(board=board)
    count = aa.check_and_answer()

    assert count == 1
    board.add_comment.assert_called_once()
    board.move_task.assert_called_once_with("t1", "To Do")


def test_recent_card_is_not_answered():
    board = MagicMock()
    board.list_tasks.return_value = [_TASK]
    board.get_list_entry_time.return_value = _NEW_TIME

    aa = _make(board=board)
    count = aa.check_and_answer()

    assert count == 0
    board.add_comment.assert_not_called()


def test_no_questions_comment_requeues_anyway():
    board = MagicMock()
    board.list_tasks.return_value = [_TASK]
    board.get_list_entry_time.return_value = _OLD_TIME
    board.get_comments.return_value = []

    aa = _make(board=board)
    count = aa.check_and_answer()

    assert count == 1
    board.move_task.assert_called_once_with("t1", "To Do")
    board.add_comment.assert_not_called()


def test_empty_waiting_list():
    board = MagicMock()
    board.list_tasks.return_value = []
    aa = _make(board=board)
    assert aa.check_and_answer() == 0
