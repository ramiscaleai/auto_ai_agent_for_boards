"""Real E2E: creates a Trello card, builds the agent prompt, verifies prompt context and card move."""
import os
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from ai_agents.base import AgentResult
from boards.trello_board import TrelloBoard
from git_workflow import BranchNamer
from orchestrator.task_runner import TaskRunner
from repo_identifier import RepoIdentifier, RepoRegistry
from repo_identifier.models import RepoMatch

_REQUIRED = [
    "TRELLO_API_KEY",
    "TRELLO_TOKEN",
    "TRELLO_BOARD_ID",
    "TRELLO_TO_DO_LIST_NAME",
    "TRELLO_TO_REVIEW_LIST_NAME",
]


@pytest.fixture(scope="module", autouse=True)
def _e2e_gate():
    if os.environ.get("E2E") != "1":
        pytest.skip("E2E tests gated by E2E=1")
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        pytest.skip(f"Missing env vars: {missing}")


@pytest.fixture(scope="module")
def board():
    return TrelloBoard(
        api_key=os.environ["TRELLO_API_KEY"],
        token=os.environ["TRELLO_TOKEN"],
        board_id=os.environ["TRELLO_BOARD_ID"],
    )


@pytest.fixture(scope="module")
def git_repo(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("trello_e2e_repo")
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "e2e@test.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "E2E"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# E2E test repo")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def task_runner(board, git_repo, tmp_path_factory):
    repos_md = tmp_path_factory.mktemp("repos") / "repos.md"
    repos_md.write_text(textwrap.dedent(f"""\
        # Repositories

        ## e2e_target
        path: {git_repo}
        description: E2E test git repository
        tags: [test]
    """))
    registry = RepoRegistry.from_file(repos_md)
    llm = MagicMock()
    llm.ask.return_value = RepoMatch(names=["e2e_target"], rationale="only repo")
    identifier = RepoIdentifier(registry, llm)
    branch_namer = MagicMock(spec=BranchNamer)
    branch_namer.name.return_value = "task/e2e-test"
    runner = MagicMock()
    runner.run.return_value = AgentResult(
        success=True,
        summary="Prompt captured.",
        files_changed=[],
        output="",
        cost_usd=None,
        duration_s=0.1,
        error=None,
        questions=None,
    )
    return TaskRunner(
        board=board,
        identifier=identifier,
        runner=runner,
        branch_namer=branch_namer,
        to_review_list=os.environ["TRELLO_TO_REVIEW_LIST_NAME"],
    )


def test_full_trello_prompt_context(board, task_runner, git_repo):
    to_do = os.environ["TRELLO_TO_DO_LIST_NAME"]
    to_review = os.environ["TRELLO_TO_REVIEW_LIST_NAME"]
    label_id = None

    card = board.create_task(
        to_do,
        name="[E2E TEST] Prompt context",
        description="Use the full Trello card context in the generated prompt.",
    )

    try:
        label_id = _create_label(board, "e2e-prompt-context")
        board._request("POST", f"/cards/{card.id}/idLabels", params={"value": label_id})
        checklist_id = _create_checklist(board, card.id, "Release checklist")
        board._request("POST", f"/checklists/{checklist_id}/checkItems", params={"name": "Document prompt", "checked": "true"})
        board.add_comment(card.id, "First human clarification.")
        board.add_comment(card.id, "[AI Agent] Questions about this task:\n\n1. Which repo owns this?")

        enriched_card = next(task for task in board.list_tasks(to_do) if task.id == card.id)
        outcome = task_runner.run(enriched_card)

        assert outcome.status == "done", f"Unexpected status: {outcome.status} — {outcome.error}"

        prompt = task_runner._runner.run.call_args[0][0].prompt
        assert "Task: [E2E TEST] Prompt context" in prompt
        assert "List: To Do" in prompt
        assert "Labels: e2e-prompt-context" in prompt
        assert "Checklist:\n[x] Document prompt" in prompt
        assert "Discussion:" in prompt
        assert "First human clarification." in prompt
        assert "[AI Agent] Questions about this task:" in prompt
        assert "[BOT]" in prompt
        assert "Repo context:" in prompt
        assert "Routing rationale: only repo" in prompt
        assert "Current branch: task/e2e-test" in prompt

        positions = [
            prompt.index("Task: [E2E TEST] Prompt context"),
            prompt.index("URL: "),
            prompt.index("List: To Do"),
            prompt.index("Labels: e2e-prompt-context"),
            prompt.index("Description:\nUse the full Trello card context in the generated prompt."),
            prompt.index("Checklist:\n[x] Document prompt"),
            prompt.index("Discussion:"),
            prompt.index("Repo context:"),
            prompt.index("Instructions:"),
        ]
        assert positions == sorted(positions)
        assert prompt.index("First human clarification.") < prompt.index("[AI Agent] Questions about this task:")

        tasks_in_review = [t.id for t in board.list_tasks(to_review)]
        assert card.id in tasks_in_review, f"Card {card.id} not found in {to_review!r}. Review tasks: {tasks_in_review}"
        subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True, capture_output=True)

    finally:
        _cleanup_card(board, card.id)
        if label_id:
            _cleanup_label(board, label_id)
        _cleanup_branch(git_repo, "task/e2e-test")


def _create_label(board: TrelloBoard, name: str) -> str:
    label = board._request(
        "POST",
        "/labels",
        params={"idBoard": board._board_id, "name": name, "color": "green"},
    )
    return label["id"]


def _create_checklist(board: TrelloBoard, card_id: str, name: str) -> str:
    checklist = board._request("POST", f"/cards/{card_id}/checklists", params={"name": name})
    return checklist["id"]


def _cleanup_card(board: TrelloBoard, card_id: str) -> None:
    try:
        board._request("DELETE", f"/cards/{card_id}")
    except Exception as exc:
        print(f"Warning: could not delete test card {card_id}: {exc}")


def _cleanup_label(board: TrelloBoard, label_id: str) -> None:
    try:
        board._request("DELETE", f"/labels/{label_id}")
    except Exception as exc:
        print(f"Warning: could not delete test label {label_id}: {exc}")


def _cleanup_branch(repo: Path, branch: str) -> None:
    subprocess.run(["git", "branch", "-D", branch], cwd=repo, capture_output=True)
