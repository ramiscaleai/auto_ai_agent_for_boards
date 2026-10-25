from unittest.mock import MagicMock

import pytest

from git_workflow.branch_namer import BranchNamer, _fallback_slug, _hex_suffix


def _namer(words: list[str]) -> BranchNamer:
    llm = MagicMock()
    llm.ask.return_value = MagicMock(words=words)
    return BranchNamer(llm)


def test_basic_slug():
    n = _namer(["add", "payment", "integration"])
    result = n.name("Add payment integration", "0123456789abcdef0123fbd1")
    assert result == "task/add-payment-integration-fbd1"


def test_extra_words_appended():
    n = _namer(["fix", "login", "redirect", "after", "oauth"])
    result = n.name("Fix login redirect after OAuth", "abc00000000000000000abcd")
    assert result == "task/fix-login-redirect-after-oauth-abcd"


def test_words_capped_at_6():
    n = _namer(["a", "b", "c", "d", "e", "f", "g"])
    result = n.name("Very long title here", "0000000000000000deadbeef")
    assert result == "task/a-b-c-d-e-f-beef"


def test_llm_failure_falls_back():
    llm = MagicMock()
    llm.ask.side_effect = RuntimeError("no connection")
    n = BranchNamer(llm)
    result = n.name("Refactor auth middleware", "cafebabe1234")
    assert result.startswith("task/refactor-auth-middleware")
    assert result.endswith("-1234")


def test_hex_suffix_extracts_last4():
    assert _hex_suffix("0123456789abcdef0123fbd1") == "fbd1"
    assert _hex_suffix("ABC123") == "c123"


def test_fallback_slug_uses_first3_words():
    assert _fallback_slug("Fix login bug in prod") == "fix-login-bug"
    assert _fallback_slug("Short") == "short"
