import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from git_workflow._git import branch_exists, changed_files, current_branch, has_changes, run_git

CWD = Path("/fake/repo")


def _cp(stdout="", returncode=0):
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.stdout = stdout
    cp.stderr = ""
    cp.returncode = returncode
    cp.check_returncode = MagicMock(side_effect=subprocess.CalledProcessError(returncode, "git") if returncode != 0 else None)
    return cp


@patch("git_workflow._git.subprocess.run")
def test_run_git_success(mock_run):
    mock_run.return_value = _cp(stdout="main\n")
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], CWD)
    assert result.stdout == "main\n"
    mock_run.assert_called_once()


@patch("git_workflow._git.subprocess.run")
def test_run_git_failure_raises(mock_run):
    cp = _cp(returncode=1)
    mock_run.return_value = cp
    with pytest.raises(subprocess.CalledProcessError):
        run_git(["bad"], CWD, check=True)


@patch("git_workflow._git.subprocess.run")
def test_current_branch(mock_run):
    mock_run.return_value = _cp(stdout="feat/x\n")
    assert current_branch(CWD) == "feat/x"


@patch("git_workflow._git.subprocess.run")
def test_branch_exists_true(mock_run):
    mock_run.return_value = _cp(stdout="  task/abc\n")
    assert branch_exists(CWD, "task/abc") is True


@patch("git_workflow._git.subprocess.run")
def test_branch_exists_false(mock_run):
    mock_run.return_value = _cp(stdout="")
    assert branch_exists(CWD, "task/xyz") is False


@patch("git_workflow._git.subprocess.run")
def test_has_changes_true(mock_run):
    mock_run.return_value = _cp(stdout=" M file.py\n")
    assert has_changes(CWD) is True


@patch("git_workflow._git.subprocess.run")
def test_has_changes_false(mock_run):
    mock_run.return_value = _cp(stdout="")
    assert has_changes(CWD) is False


@patch("git_workflow._git.subprocess.run")
def test_changed_files(mock_run):
    mock_run.return_value = _cp(stdout="a.py\nb.py\n")
    files = changed_files(CWD, "main")
    assert files == [Path("a.py"), Path("b.py")]
