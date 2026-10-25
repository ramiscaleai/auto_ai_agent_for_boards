from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repo_identifier.identifier import RepoIdentifier
from repo_identifier.models import RepoEntry, RepoMatch
from repo_identifier.registry import RepoRegistry

_BACKEND = RepoEntry(name="backend", path=Path("/be"), description="API server", tags=("python",))
_FRONTEND = RepoEntry(name="frontend", path=Path("/fe"), description="React UI", tags=("react",))


def _registry(*entries: RepoEntry) -> RepoRegistry:
    return RepoRegistry(list(entries))


def _llm(names: list[str]) -> MagicMock:
    llm = MagicMock()
    llm.ask.return_value = RepoMatch(names=names, rationale="test")
    return llm


def test_single_repo_skips_llm():
    reg = _registry(_BACKEND)
    llm = _llm([])
    result = RepoIdentifier(reg, llm).identify("fix a bug")
    assert result == [_BACKEND]
    llm.ask.assert_not_called()


def test_llm_picks_correct_repo():
    reg = _registry(_BACKEND, _FRONTEND)
    llm = _llm(["backend"])
    result = RepoIdentifier(reg, llm).identify("fix API endpoint")
    assert result == [_BACKEND]


def test_llm_picks_multiple_repos():
    reg = _registry(_BACKEND, _FRONTEND)
    llm = _llm(["backend", "frontend"])
    result = RepoIdentifier(reg, llm).identify("full-stack feature")
    assert set(e.name for e in result) == {"backend", "frontend"}


def test_unknown_name_falls_back_to_first():
    reg = _registry(_BACKEND, _FRONTEND)
    llm = _llm(["unknown_repo"])
    result = RepoIdentifier(reg, llm).identify("something")
    assert result == [_BACKEND]


def test_empty_registry_returns_empty():
    reg = _registry()
    llm = _llm([])
    result = RepoIdentifier(reg, llm).identify("anything")
    assert result == []
    llm.ask.assert_not_called()
