from unittest.mock import MagicMock

from boards.board import Task
from auto_answer import StuckHandler, format_questions

_TASK = Task(id="t1", name="Fix auth", description="desc", list_name="To Do", url="")


def test_format_questions_numbered():
    result = format_questions(["What DB?", "Which port?"])
    assert "1. What DB?" in result
    assert "2. Which port?" in result


def test_format_questions_prefix():
    result = format_questions(["Q1"])
    assert "[AI Agent]" in result


def test_handle_adds_comment_and_moves():
    board = MagicMock()
    handler = StuckHandler(board=board, waiting_list="Waiting for answers")
    handler.handle(_TASK, ["What DB?", "Which port?"])
    board.add_comment.assert_called_once()
    board.move_task.assert_called_once_with("t1", "Waiting for answers")


def test_handle_comment_contains_questions():
    board = MagicMock()
    handler = StuckHandler(board=board, waiting_list="Waiting for answers")
    handler.handle(_TASK, ["What DB?"])
    comment_text = board.add_comment.call_args[0][1]
    assert "What DB?" in comment_text
