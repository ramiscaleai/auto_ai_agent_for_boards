import textwrap
from pathlib import Path

import pytest

from repo_identifier.registry import RepoRegistry


SAMPLE = textwrap.dedent("""\
    # Repositories

    ## backend
    path: /srv/repos/backend
    description: Python FastAPI backend
    tags: [python, api]
    trello_board_id: board-backend

    ## frontend
    path: /srv/repos/frontend
    description: React SPA
    tags: [react, ts]
""")

MISSING_FIELDS = textwrap.dedent("""\
    # Repositories

    ## broken
    description: No path here
""")


@pytest.fixture()
def repos_file(tmp_path) -> Path:
    p = tmp_path / "repos.md"
    p.write_text(SAMPLE)
    return p


def test_load_two_repos(repos_file):
    reg = RepoRegistry.from_file(repos_file)
    assert len(reg) == 2


def test_repo_names(repos_file):
    reg = RepoRegistry.from_file(repos_file)
    names = {e.name for e in reg.all()}
    assert names == {"backend", "frontend"}


def test_repo_path(repos_file):
    reg = RepoRegistry.from_file(repos_file)
    be = reg.get("backend")
    assert be is not None
    assert str(be.path) == "/srv/repos/backend"


def test_repo_tags(repos_file):
    reg = RepoRegistry.from_file(repos_file)
    fe = reg.get("frontend")
    assert fe is not None
    assert "react" in fe.tags


def test_repo_optional_trello_board_id(repos_file):
    reg = RepoRegistry.from_file(repos_file)
    be = reg.get("backend")
    assert be is not None
    assert be.trello_board_id == "board-backend"


def test_get_unknown_returns_none(repos_file):
    reg = RepoRegistry.from_file(repos_file)
    assert reg.get("nonexistent") is None


def test_missing_path_skipped(tmp_path):
    p = tmp_path / "repos.md"
    p.write_text(MISSING_FIELDS)
    reg = RepoRegistry.from_file(p)
    assert len(reg) == 0


def test_empty_file(tmp_path):
    p = tmp_path / "repos.md"
    p.write_text("# Repos\n")
    reg = RepoRegistry.from_file(p)
    assert len(reg) == 0
