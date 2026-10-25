from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from git_workflow.workspace import MergeConflictError, TaskWorkspace

REPO = Path("/fake/repo")
MODULE = "git_workflow.workspace"


def _ws(task_id="abc123", base="main"):
    return TaskWorkspace(repo_path=REPO, task_id=task_id, base_branch=base)


@patch(f"{MODULE}.branch_exists", return_value=False)
@patch(f"{MODULE}.current_branch", return_value="main")
@patch(f"{MODULE}.run_git")
def test_enter_creates_branch(mock_git, _cb, _be):
    with _ws() as ws:
        assert ws.branch == "task/abc123"
    calls = [str(c.args[0]) for c in mock_git.call_args_list]
    assert any("checkout" in c and "-b" in c for c in calls)


@patch(f"{MODULE}.branch_exists", return_value=True)
@patch(f"{MODULE}.current_branch", return_value="main")
@patch(f"{MODULE}.run_git")
def test_enter_reuses_existing_branch(mock_git, _cb, _be):
    with _ws():
        pass
    calls = [c.args[0] for c in mock_git.call_args_list]
    assert not any("-b" in c for c in calls)


@patch(f"{MODULE}.has_changes", return_value=True)
@patch(f"{MODULE}.branch_exists", return_value=False)
@patch(f"{MODULE}.current_branch", return_value="main")
@patch(f"{MODULE}.run_git")
def test_stage_and_commit_with_changes(mock_git, _cb, _be, _hc):
    with _ws() as ws:
        result = ws.stage_and_commit("progress")
    assert result is True
    calls = [c.args[0] for c in mock_git.call_args_list]
    assert any("commit" in c for c in calls)


@patch(f"{MODULE}.has_changes", return_value=False)
@patch(f"{MODULE}.branch_exists", return_value=False)
@patch(f"{MODULE}.current_branch", return_value="main")
@patch(f"{MODULE}.run_git")
def test_stage_and_commit_no_changes(mock_git, _cb, _be, _hc):
    with _ws() as ws:
        result = ws.stage_and_commit("nothing")
    assert result is False


def _mock_merge_success():
    cp = MagicMock()
    cp.returncode = 0
    return cp


def _mock_merge_conflict():
    cp = MagicMock()
    cp.returncode = 1
    cp.stderr = "CONFLICT"
    return cp


@patch(f"{MODULE}.branch_exists", return_value=False)
@patch(f"{MODULE}.current_branch", return_value="main")
@patch(f"{MODULE}.run_git")
def test_merge_main_in_conflict_raises(mock_git, _cb, _be):
    calls = [_mock_merge_success()]  # enter: only checkout -b
    conflict_cp = _mock_merge_conflict()
    abort_cp = MagicMock(returncode=0)
    mock_git.side_effect = calls + [conflict_cp, abort_cp]
    with _ws() as ws:
        with pytest.raises(MergeConflictError):
            ws.merge_main_in()


@patch(f"{MODULE}.changed_files", return_value=[Path("x.py")])
@patch(f"{MODULE}.branch_exists", return_value=False)
@patch(f"{MODULE}.current_branch", return_value="main")
@patch(f"{MODULE}.run_git")
def test_get_changed_files(mock_git, _cb, _be, _cf):
    with _ws() as ws:
        files = ws.get_changed_files()
    assert files == [Path("x.py")]
