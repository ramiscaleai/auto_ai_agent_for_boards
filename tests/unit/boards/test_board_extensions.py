"""Unit tests for Comment dataclass and TrelloBoard.get_comments / get_list_entry_time."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from boards.board import Attachment, ChecklistItem, Comment
from boards.trello_board import TrelloBoard


def _board() -> TrelloBoard:
    b = TrelloBoard.__new__(TrelloBoard)
    b._auth = {"key": "k", "token": "t"}
    b._board_id = "bid"
    b._session = MagicMock()
    b._list_id_by_name = {}
    return b


def test_comment_dataclass():
    c = Comment(id="c1", author="Alice", text="hello", created_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert c.id == "c1"
    assert c.author == "Alice"


def test_to_task_captures_labels_due_checklist_and_attachments():
    board = _board()
    task = board._to_task(
        {
            "id": "card1",
            "name": "Implement prompt enrichment",
            "desc": "Details",
            "url": "https://trello.com/c/card1",
            "due": "2024-06-20T09:30:00Z",
            "labels": [{"name": "backend"}, {"name": "ai"}],
            "checklists": [
                {"checkItems": [{"name": "Prompt", "state": "complete"}, {"name": "Tests", "state": "incomplete"}]}
            ],
            "attachments": [
                {"name": "spec.md", "url": "https://files.example/spec.md"},
                {"name": "", "url": "https://files.example/image.png"},
            ],
        },
        "To Do",
    )

    assert task.labels == ("backend", "ai")
    assert task.due_at == datetime(2024, 6, 20, 9, 30)
    assert task.checklist_items == (
        ChecklistItem(name="Prompt", checked=True),
        ChecklistItem(name="Tests", checked=False),
    )
    assert task.attachments == (
        Attachment(name="spec.md", url="https://files.example/spec.md"),
        Attachment(name="", url="https://files.example/image.png"),
    )


def test_get_comments_returns_oldest_first():
    board = _board()
    actions = [
        {"id": "a2", "date": "2024-01-02T10:00:00Z", "memberCreator": {"fullName": "Bob"}, "data": {"text": "second"}},
        {"id": "a1", "date": "2024-01-01T10:00:00Z", "memberCreator": {"fullName": "Alice"}, "data": {"text": "first"}},
    ]
    with patch.object(board, "_request", return_value=actions):
        comments = board.get_comments("card1")
    assert comments[0].text == "first"
    assert comments[1].text == "second"


def test_get_comments_empty():
    board = _board()
    with patch.object(board, "_request", return_value=[]):
        comments = board.get_comments("card1")
    assert comments == []


def test_get_list_entry_time_from_actions():
    board = _board()
    actions = [{"date": "2024-06-15T12:00:00Z"}]
    with patch.object(board, "_request", return_value=actions):
        dt = board.get_list_entry_time("card1")
    assert dt == datetime(2024, 6, 15, 12, 0, 0)


def test_get_list_entry_time_fallback_to_card():
    board = _board()

    def fake_request(method, path, params=None, data=None):
        if "filter" in (params or {}):
            return []
        return {"dateLastActivity": "2024-03-01T08:00:00Z"}

    with patch.object(board, "_request", side_effect=fake_request):
        dt = board.get_list_entry_time("card1")
    assert dt == datetime(2024, 3, 1, 8, 0, 0)
