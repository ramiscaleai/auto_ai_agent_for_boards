"""E2E: TaskWorkspace runs real git operations in a temp repo."""
import subprocess
from pathlib import Path

import pytest

from git_workflow import MergeConflictError, TaskWorkspace
from git_workflow._git import current_branch


def _cur(path: Path) -> str:
    return current_branch(path)


def test_creates_task_branch(git_repo):
    with TaskWorkspace(git_repo, "t001") as ws:
        assert _cur(git_repo) == "task/t001"
        assert ws.branch == "task/t001"


def test_stage_and_commit(git_repo):
    with TaskWorkspace(git_repo, "t002") as ws:
        (git_repo / "new.py").write_text("x = 1")
        committed = ws.stage_and_commit("add new.py")
    assert committed is True
    log = subprocess.run(["git", "log", "--oneline"], cwd=git_repo, capture_output=True, text=True)
    assert "add new.py" in log.stdout


def test_no_changes_does_not_commit(git_repo):
    with TaskWorkspace(git_repo, "t003") as ws:
        committed = ws.stage_and_commit("nothing to commit")
    assert committed is False


def test_get_changed_files(git_repo):
    with TaskWorkspace(git_repo, "t004") as ws:
        (git_repo / "feature.py").write_text("y = 2")
        ws.stage_and_commit("add feature.py")
        files = ws.get_changed_files()
    assert Path("feature.py") in files


def test_merge_main_in(git_repo):
    # Add a commit to main after branching
    with TaskWorkspace(git_repo, "t005") as ws:
        # Add commit on task branch
        (git_repo / "task.py").write_text("task = 1")
        ws.stage_and_commit("task work")
        # Switch to main, add a new file, switch back
        subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True, capture_output=True)
        (git_repo / "main_extra.py").write_text("extra = 1")
        subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "main extra"], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", ws.branch], cwd=git_repo, check=True, capture_output=True)
        # Now merge main in — should succeed
        ws.merge_main_in()
        assert (git_repo / "main_extra.py").exists()


def test_merge_back_to_main(git_repo):
    with TaskWorkspace(git_repo, "t006") as ws:
        (git_repo / "done.py").write_text("done = True")
        ws.stage_and_commit("task complete")
        ws.merge_back_to_main()
    # Verify done.py is on main
    subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True, capture_output=True)
    assert (git_repo / "done.py").exists()


def test_reuses_existing_branch(git_repo):
    subprocess.run(["git", "checkout", "-b", "task/t007"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=git_repo, check=True, capture_output=True)
    with TaskWorkspace(git_repo, "t007") as ws:
        assert _cur(git_repo) == "task/t007"
