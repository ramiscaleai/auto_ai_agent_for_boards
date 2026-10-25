"""Live E2E: seed a small backlog for this repo against a throwaway list
on the real Trello board, verify count/area mix, clean up.

Gated by E2E=1 so regular CI does not hit the board or the LLM.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from ai_agents import AgentRegistry  # noqa: E402
from boards.backlog_seed_intent import parse_seed_intent  # noqa: E402
from boards.repo_backlog_seeder import RepoBacklogSeeder  # noqa: E402
from boards.trello_board import TrelloBoard  # noqa: E402
from repo_identifier.models import RepoEntry  # noqa: E402

_REQUIRED = ["TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_BOARD_ID"]
_API = "https://api.trello.com/1"


@pytest.fixture(scope="module", autouse=True)
def _e2e_gate():
    if os.environ.get("E2E") != "1":
        pytest.skip("E2E tests gated by E2E=1")
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        pytest.skip(f"Missing env vars: {missing}")


def _auth():
    return {"key": os.environ["TRELLO_API_KEY"], "token": os.environ["TRELLO_TOKEN"]}


@pytest.fixture(scope="module")
def board_id() -> str:
    short = os.environ["TRELLO_BOARD_ID"]
    r = requests.get(f"{_API}/boards/{short}", params={**_auth(), "fields": "id"}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


@pytest.fixture()
def throwaway_list(board_id):
    name = f"e2e-seed-{int(time.time())}"
    r = requests.post(
        f"{_API}/lists", params={**_auth(), "name": name, "idBoard": board_id}, timeout=15,
    )
    r.raise_for_status()
    list_id = r.json()["id"]
    yield name, list_id
    _archive_list_and_cards(list_id)


def _archive_list_and_cards(list_id: str) -> None:
    try:
        cards = requests.get(f"{_API}/lists/{list_id}/cards", params=_auth(), timeout=15).json()
        for card in cards:
            requests.delete(f"{_API}/cards/{card['id']}", params=_auth(), timeout=15)
        requests.put(
            f"{_API}/lists/{list_id}/closed", params={**_auth(), "value": "true"}, timeout=15,
        )
    except Exception:  # noqa: BLE001 — cleanup must never fail the test
        pass


@pytest.fixture(scope="module")
def structured_llm():
    agents_yml = Path(__file__).resolve().parents[3] / "config" / "agents.yml"
    registry = AgentRegistry.load(agents_yml, env=dict(os.environ))
    return registry.build_structured_llm()


@pytest.fixture(scope="module")
def this_repo() -> RepoEntry:
    return RepoEntry(
        name="auto_ai_agent_for_boards",
        path=Path(__file__).resolve().parents[3],
        description="The autonomous AI agent that picks Trello tasks and implements them",
        tags=("python", "ai", "trello", "automation"),
        trello_board_id=None,
    )


def test_seeder_creates_requested_cards_on_real_board(
    board_id, throwaway_list, structured_llm, this_repo,
):
    list_name, _list_id = throwaway_list
    card_title = "add top 6 tasks to Trello Backlog for auto_ai_agent_for_boards repo"
    card_desc = "at least 3 for backend and at least 2 for frontend which is not trello."
    intent = parse_seed_intent(card_title, card_desc)
    assert intent is not None and intent.count == 6

    board = TrelloBoard(
        api_key=os.environ["TRELLO_API_KEY"],
        token=os.environ["TRELLO_TOKEN"],
        board_id=board_id,
    )
    seeder = RepoBacklogSeeder(llm=structured_llm, max_generation_retries=2)

    outcome = seeder.seed(this_repo, intent, board, list_name)

    assert outcome.success, f"Seed failed: {outcome.reason}"
    assert len(outcome.created) == 6
    landed = board.list_tasks(list_name)
    assert len(landed) == 6

    areas = [name.split("]")[0][1:] for name in (t.name for t in landed) if name.startswith("[")]
    assert sum(a == "Backend" for a in areas) >= 3
    assert sum(a == "Frontend" for a in areas) >= 2
    for task in landed:
        if task.name.startswith("[Frontend]"):
            haystack = (task.name + task.description).lower()
            assert "trello" not in haystack, f"frontend card targets Trello: {task.name}"


def test_seeder_is_idempotent_on_rerun(
    board_id, throwaway_list, structured_llm, this_repo,
):
    list_name, _list_id = throwaway_list
    card_title = "add top 4 tasks to Trello Backlog for auto_ai_agent_for_boards repo"
    intent = parse_seed_intent(card_title, "at least 2 for backend")
    assert intent is not None

    board = TrelloBoard(
        api_key=os.environ["TRELLO_API_KEY"],
        token=os.environ["TRELLO_TOKEN"],
        board_id=board_id,
    )
    seeder = RepoBacklogSeeder(llm=structured_llm, max_generation_retries=2)

    first = seeder.seed(this_repo, intent, board, list_name)
    assert first.success and len(first.created) == 4
    initial_count = len(board.list_tasks(list_name))

    second = seeder.seed(this_repo, intent, board, list_name)
    assert len(board.list_tasks(list_name)) >= initial_count
    assert len(second.skipped_existing) >= 1 or len(second.created) + initial_count == len(
        board.list_tasks(list_name)
    )
