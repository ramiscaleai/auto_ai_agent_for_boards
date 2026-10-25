"""E2E: AutoAnswerer generates real LLM answers for stuck tasks."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_agents import AgentRegistry
from auto_answer import AutoAnswerer
from auto_answer.stuck_handler import _PREFIX
from boards.board import Comment, Task

_OLD_TIME = datetime.now(timezone.utc) - timedelta(hours=72)
_TASK = Task(id="t1", name="Add user auth", description="Implement JWT auth for the API", list_name="Waiting", url="")
_QUESTIONS = "1. Which JWT library should I use?\n2. Should tokens expire after 24h or 1h?"
_COMMENT_TEXT = f"{_PREFIX}{_QUESTIONS}"


@pytest.fixture(scope="module")
def llm(tmp_path_factory):
    yaml_path = Path(__file__).resolve().parents[3] / "config" / "agents.yml"
    reg = AgentRegistry.load(yaml_path, env={})
    return reg.build_structured_llm()


def test_auto_answer_generates_text(llm, tmp_path):
    board = MagicMock()
    board.list_tasks.return_value = [_TASK]
    board.get_list_entry_time.return_value = _OLD_TIME
    board.get_comments.return_value = [
        Comment(id="c1", author="AI Agent", text=_COMMENT_TEXT, created_at=_OLD_TIME)
    ]

    aa = AutoAnswerer(board=board, waiting_list="Waiting", to_do_list="To Do", auto_answer_hours=48, llm=llm)
    count = aa.check_and_answer()

    assert count == 1
    board.add_comment.assert_called_once()
    comment_text = board.add_comment.call_args[0][1]
    assert "JWT" in comment_text or len(comment_text) > 50, f"Unexpectedly short answer: {comment_text!r}"
    board.move_task.assert_called_once_with("t1", "To Do")
