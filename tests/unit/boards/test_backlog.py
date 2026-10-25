from unittest.mock import MagicMock

from boards.backlog import current_repo_backlog, seed_backlog
from boards.board import Task


def test_current_repo_backlog_has_expected_size_and_mix():
    tasks = current_repo_backlog()

    assert len(tasks) == 30
    assert sum(task.area == "Backend" for task in tasks) >= 10
    assert sum(task.area == "Frontend" for task in tasks) >= 5
    assert len({task.card_name for task in tasks}) == len(tasks)


def test_frontend_tasks_do_not_target_trello():
    tasks = current_repo_backlog()

    frontend_text = " ".join(task.card_description.lower() for task in tasks if task.area == "Frontend")
    assert "trello" not in frontend_text


def test_seed_backlog_skips_existing_cards_and_creates_missing_ones():
    board = MagicMock()
    existing = Task(
        id="1",
        name="[Backend] Claim cards before execution to prevent duplicate workers",
        description="",
        list_name="Backlog",
        url="",
    )
    board.list_tasks.return_value = [existing]

    result = seed_backlog(board, "Backlog")

    assert len(result.created) == 29
    assert len(result.skipped) == 1
    board.create_task.assert_called()


def test_seed_backlog_dry_run_does_not_create_cards():
    board = MagicMock()
    board.list_tasks.return_value = []

    result = seed_backlog(board, "Backlog", dry_run=True)

    assert len(result.created) == 30
    board.create_task.assert_not_called()
