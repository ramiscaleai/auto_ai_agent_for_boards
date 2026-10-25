from pathlib import Path
from unittest.mock import patch

from repo_identifier.models import RepoEntry
from orchestrator.trello_resolver import TrelloBoardResolver


def _resolver() -> TrelloBoardResolver:
    return TrelloBoardResolver(
        default_api_key="default-key",
        default_token="default-token",
        default_board_id="default-board",
        default_to_do_list="To Do",
        default_to_review_list="To Review",
        default_waiting_list="Waiting for answers",
    )


@patch("orchestrator.trello_resolver.TrelloBoard")
def test_resolve_prefers_repo_env_when_complete(mock_board, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text(
        "\n".join(
            [
                "TRELLO_API_KEY=repo-key",
                "TRELLO_TOKEN=repo-token",
                "TRELLO_BOARD_ID=repo-board",
                "TRELLO_TO_REVIEW_LIST_NAME=Repo Review",
                "TRELLO_WAITING_LIST_NAME=Repo Waiting",
            ]
        ),
        encoding="utf-8",
    )
    entry = RepoEntry(name="repo", path=repo, description="desc", trello_board_id="fallback-board")

    resolved = _resolver().resolve(entry)

    mock_board.assert_called_once_with(api_key="repo-key", token="repo-token", board_id="repo-board")
    assert resolved.source == f"{repo}/.env"
    assert resolved.to_review_list == "Repo Review"
    assert resolved.waiting_list == "Repo Waiting"


@patch("orchestrator.trello_resolver.TrelloBoard")
def test_resolve_uses_repos_md_board_when_repo_env_incomplete(mock_board, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("TRELLO_BOARD_ID=partial-board\n", encoding="utf-8")
    entry = RepoEntry(name="repo", path=repo, description="desc", trello_board_id="fallback-board")

    resolved = _resolver().resolve(entry)

    mock_board.assert_called_once_with(
        api_key="default-key",
        token="default-token",
        board_id="fallback-board",
    )
    assert resolved.source == "repos.md"
    assert resolved.to_review_list == "To Review"


@patch("orchestrator.trello_resolver.TrelloBoard")
def test_resolve_falls_back_to_default_board(mock_board, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    entry = RepoEntry(name="repo", path=repo, description="desc")

    resolved = _resolver().resolve(entry)

    mock_board.assert_called_once_with(
        api_key="default-key",
        token="default-token",
        board_id="default-board",
    )
    assert resolved.source == "default"
