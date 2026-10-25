"""E2E: full orchestration — real agents, real git, mock Trello board."""
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_agents import AgentRegistry, AgentRunner, CostGuard, NoOpTracer
from boards.board import Task
from orchestrator.task_runner import TaskRunner
from repo_identifier import RepoIdentifier, RepoRegistry


@pytest.fixture(scope="module")
def git_repo(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("orch_repo")
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "ci@test.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    yaml_path = Path(__file__).resolve().parents[3] / "config" / "agents.yml"
    reg = AgentRegistry.load(yaml_path, env={})
    guard = CostGuard(
        per_task_cap_usd=0.10,
        daily_cap_usd=1.00,
        state_path=tmp_path_factory.mktemp("cost") / "spend.json",
    )
    return AgentRunner(registry=reg, cost_guard=guard, tracer=NoOpTracer())


def test_full_task_cycle(git_repo, runner, tmp_path_factory):
    """Agent gets a task, implements it in a real git repo, card moves to To Review."""
    repos_md = tmp_path_factory.mktemp("repos") / "repos.md"
    repos_md.write_text(textwrap.dedent(f"""\
        # Repositories

        ## target
        path: {git_repo}
        description: Test git repository
        tags: [python]
    """))

    registry = RepoRegistry.from_file(repos_md)
    llm = MagicMock()
    from repo_identifier.models import RepoMatch
    llm.ask.return_value = RepoMatch(names=["target"], rationale="only one repo")
    identifier = RepoIdentifier(registry, llm)

    board = MagicMock()
    board.add_comment = MagicMock()
    board.move_task = MagicMock()

    task = Task(
        id="test-task-001",
        name='Create hello.py',
        description='Create a Python file named hello.py containing exactly: print("hello world")',
        list_name="To Do",
        url="https://trello.com/c/test",
    )

    tr = TaskRunner(board=board, identifier=identifier, runner=runner, to_review_list="To Review")
    outcome = tr.run(task)

    assert outcome.status in ("done", "questions"), f"Unexpected status: {outcome.status} — {outcome.error}"
    if outcome.status == "done":
        subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True, capture_output=True)
        assert (git_repo / "hello.py").exists(), "hello.py not found on main after merge"
        board.move_task.assert_called_once_with("test-task-001", "To Review")
