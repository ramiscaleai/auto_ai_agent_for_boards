from pathlib import Path

from repo_identifier.models import RepoEntry, RepoMatch


def test_repo_entry_summary_with_tags():
    e = RepoEntry(name="myrepo", path=Path("/tmp/myrepo"), description="A test repo", tags=("python", "ai"))
    s = e.summary()
    assert "[myrepo]" in s
    assert "python" in s
    assert "A test repo" in s


def test_repo_entry_summary_no_tags():
    e = RepoEntry(name="myrepo", path=Path("/tmp/myrepo"), description="A test repo")
    assert "—" in e.summary()


def test_repo_entry_is_frozen():
    e = RepoEntry(name="myrepo", path=Path("/tmp/myrepo"), description="desc")
    try:
        e.name = "other"  # type: ignore[misc]
        assert False, "should have raised"
    except Exception:
        pass


def test_repo_match_schema():
    m = RepoMatch(names=["a", "b"], rationale="both relevant")
    assert m.names == ["a", "b"]
    assert "relevant" in m.rationale
