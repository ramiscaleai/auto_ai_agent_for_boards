from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from boards.trello_board import TrelloBoard
from repo_identifier import RepoEntry

log = logging.getLogger(__name__)

_API_KEY = "TRELLO_API_KEY"
_TOKEN = "TRELLO_TOKEN"
_BOARD_ID = "TRELLO_BOARD_ID"
_TO_DO = "TRELLO_TO_DO_LIST_NAME"
_TO_REVIEW = "TRELLO_TO_REVIEW_LIST_NAME"
_WAITING = "TRELLO_WAITING_LIST_NAME"
_BACKLOG = "TRELLO_BACKLOG_LIST_NAME"


@dataclass(frozen=True)
class ResolvedTrelloBoard:
    board: TrelloBoard
    to_do_list: str
    to_review_list: str
    waiting_list: str
    source: str
    backlog_list: str = "Backlog"


class TrelloBoardResolver:
    def __init__(
        self,
        *,
        default_api_key: str,
        default_token: str,
        default_board_id: str,
        default_to_do_list: str,
        default_to_review_list: str,
        default_waiting_list: str,
        default_backlog_list: str = "Backlog",
    ) -> None:
        self._default_api_key = default_api_key
        self._default_token = default_token
        self._default_board_id = default_board_id
        self._default_to_do = default_to_do_list
        self._default_to_review = default_to_review_list
        self._default_waiting = default_waiting_list
        self._default_backlog = default_backlog_list
        self._boards: dict[tuple[str, str, str], TrelloBoard] = {}

    def resolve(self, repo: RepoEntry) -> ResolvedTrelloBoard:
        repo_env = self._load_repo_env(repo.path)
        if self._has_complete_credentials(repo_env):
            board = self._get_board(
                api_key=repo_env[_API_KEY],
                token=repo_env[_TOKEN],
                board_id=repo_env[_BOARD_ID],
            )
            resolved = ResolvedTrelloBoard(
                board=board,
                to_do_list=self._list_name(repo_env, _TO_DO, self._default_to_do),
                to_review_list=self._list_name(repo_env, _TO_REVIEW, self._default_to_review),
                waiting_list=self._list_name(repo_env, _WAITING, self._default_waiting),
                backlog_list=self._list_name(repo_env, _BACKLOG, self._default_backlog),
                source=f"{repo.path}/.env",
            )
            log.info("Resolved Trello board for repo %s from repo .env", repo.name)
            return resolved

        if repo.trello_board_id:
            board = self._get_board(
                api_key=self._default_api_key,
                token=self._default_token,
                board_id=repo.trello_board_id,
            )
            resolved = ResolvedTrelloBoard(
                board=board,
                to_do_list=self._list_name(repo_env, _TO_DO, self._default_to_do),
                to_review_list=self._list_name(repo_env, _TO_REVIEW, self._default_to_review),
                waiting_list=self._list_name(repo_env, _WAITING, self._default_waiting),
                backlog_list=self._list_name(repo_env, _BACKLOG, self._default_backlog),
                source="repos.md",
            )
            log.info("Resolved Trello board for repo %s from repos.md", repo.name)
            return resolved

        board = self._get_board(
            api_key=self._default_api_key,
            token=self._default_token,
            board_id=self._default_board_id,
        )
        log.info("Resolved Trello board for repo %s from default environment", repo.name)
        return ResolvedTrelloBoard(
            board=board,
            to_do_list=self._default_to_do,
            to_review_list=self._default_to_review,
            waiting_list=self._default_waiting,
            backlog_list=self._default_backlog,
            source="default",
        )

    def _load_repo_env(self, repo_path: Path) -> dict[str, str]:
        env_path = repo_path / ".env"
        if not env_path.is_file():
            return {}
        raw = dotenv_values(env_path)
        return {k: v for k, v in raw.items() if k and isinstance(v, str) and v.strip()}

    def _has_complete_credentials(self, env: dict[str, str]) -> bool:
        return all(env.get(key) for key in (_API_KEY, _TOKEN, _BOARD_ID))

    def _get_board(self, *, api_key: str, token: str, board_id: str) -> TrelloBoard:
        cache_key = (api_key, token, board_id)
        board = self._boards.get(cache_key)
        if board is None:
            board = TrelloBoard(api_key=api_key, token=token, board_id=board_id)
            self._boards[cache_key] = board
        return board

    @staticmethod
    def _list_name(env: dict[str, str], key: str, default: str) -> str:
        return env.get(key, default)
