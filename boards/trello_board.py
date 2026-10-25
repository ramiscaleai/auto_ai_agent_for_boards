import logging
from datetime import datetime
from typing import Any

import requests

from boards.board import Attachment, Board, ChecklistItem, Comment, Task

_API_BASE = "https://api.trello.com/1"
_TIMEOUT = 15
_AUTH_KEYS = {"key", "token"}
_log = logging.getLogger(__name__)


class TrelloAPIError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Trello API error {status}: {body}")
        self.status = status
        self.body = body


def _redact(params: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if k in _AUTH_KEYS else v) for k, v in params.items()}


def list_boards_for_token(api_key: str, token: str) -> list[dict[str, str]]:
    """Boards visible to the given token. Used for setup/debug, not part of Board ABC."""
    auth = {"key": api_key, "token": token}
    resp = requests.get(f"{_API_BASE}/members/me/boards", params=auth, timeout=_TIMEOUT)
    if not resp.ok:
        raise TrelloAPIError(resp.status_code, resp.text)
    return [{"id": b["id"], "name": b["name"]} for b in resp.json()]


class TrelloBoard(Board):
    def __init__(self, api_key: str, token: str, board_id: str):
        if not (api_key and token and board_id):
            raise ValueError("api_key, token, and board_id are all required")
        self._auth = {"key": api_key, "token": token}
        self._board_id = board_id
        self._session = requests.Session()
        self._list_id_by_name: dict[str, str] = {}

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> Any:
        merged = {**self._auth, **(params or {})}
        url = f"{_API_BASE}{path}"
        _log.debug("%s %s params=%s", method, path, _redact(merged))
        resp = self._session.request(method, url, params=merged, data=data, timeout=_TIMEOUT)
        if not resp.ok:
            _log.error("Trello %s %s failed: %s %s", method, path, resp.status_code, resp.text)
            raise TrelloAPIError(resp.status_code, resp.text)
        return resp.json() if resp.content else None

    def _refresh_list_cache(self) -> None:
        lists = self._request("GET", f"/boards/{self._board_id}/lists")
        self._list_id_by_name = {item["name"]: item["id"] for item in lists}

    def _get_list_id(self, list_name: str) -> str:
        if list_name not in self._list_id_by_name:
            self._refresh_list_cache()
        if list_name not in self._list_id_by_name:
            available = sorted(self._list_id_by_name)
            raise ValueError(f"List {list_name!r} not found on board. Available: {available}")
        return self._list_id_by_name[list_name]

    def _to_task(self, card: dict[str, Any], list_name: str) -> Task:
        labels = tuple(label["name"] for label in card.get("labels", []) if label.get("name"))
        checklist_items: list[ChecklistItem] = []
        for checklist in card.get("checklists", []):
            for item in checklist.get("checkItems", []):
                name = item.get("name", "").strip()
                if not name:
                    continue
                checklist_items.append(ChecklistItem(name=name, checked=item.get("state") == "complete"))
        attachments = tuple(
            Attachment(name=attachment.get("name", ""), url=attachment.get("url", ""))
            for attachment in card.get("attachments", [])
            if attachment.get("url")
        )
        return Task(
            id=card["id"],
            name=card["name"],
            description=card.get("desc", ""),
            list_name=list_name,
            url=card.get("url", ""),
            labels=labels,
            due_at=_parse_dt(card["due"]) if card.get("due") else None,
            checklist_items=tuple(checklist_items),
            attachments=attachments,
        )

    def get_lists(self) -> list[str]:
        self._refresh_list_cache()
        return sorted(self._list_id_by_name)

    def list_tasks(self, list_name: str) -> list[Task]:
        list_id = self._get_list_id(list_name)
        cards = self._request("GET", f"/lists/{list_id}/cards", params=_card_params())
        return [self._to_task(card, list_name) for card in cards]

    def create_task(self, list_name: str, name: str, description: str = "") -> Task:
        list_id = self._get_list_id(list_name)
        params = {"idList": list_id, "name": name, "desc": description}
        card = self._request("POST", "/cards", params=params)
        card = self._request("GET", f"/cards/{card['id']}", params=_card_params())
        _log.info("Created card %s in list %r", card["id"], list_name)
        return self._to_task(card, list_name)

    def move_task(self, task_id: str, target_list_name: str) -> None:
        list_id = self._get_list_id(target_list_name)
        self._request("PUT", f"/cards/{task_id}", params={"idList": list_id})
        _log.info("Moved card %s to list %r", task_id, target_list_name)

    def add_comment(self, task_id: str, text: str) -> None:
        self._request("POST", f"/cards/{task_id}/actions/comments", params={"text": text})
        _log.info("Added comment to card %s", task_id)

    def get_comments(self, task_id: str) -> list[Comment]:
        actions = self._request("GET", f"/cards/{task_id}/actions", params={"filter": "commentCard"})
        comments = [self._to_comment(a) for a in (actions or [])]
        return list(reversed(comments))

    def get_list_entry_time(self, task_id: str) -> datetime:
        actions = self._request("GET", f"/cards/{task_id}/actions", params={"filter": "updateCard:idList"})
        if actions:
            return _parse_dt(actions[0]["date"])
        card = self._request("GET", f"/cards/{task_id}", params={"fields": "dateLastActivity"})
        return _parse_dt(card["dateLastActivity"])

    def _to_comment(self, action: dict[str, Any]) -> Comment:
        return Comment(
            id=action["id"],
            author=action["memberCreator"].get("fullName", "unknown"),
            text=action["data"]["text"],
            created_at=_parse_dt(action["date"]),
        )


def _parse_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.rstrip("Z"))


def _card_params() -> dict[str, Any]:
    return {
        "fields": "name,desc,url,due,labels",
        "attachments": "true",
        "attachment_fields": "name,url",
        "checklists": "all",
    }
