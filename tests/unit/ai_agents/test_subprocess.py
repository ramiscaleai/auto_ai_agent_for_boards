"""Unit tests for ai_agents/_subprocess.py — shared invoke_cli helper."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_agents._subprocess import CHAT_PREFIX, _run_or_raise, invoke_cli
from ai_agents.errors import (
    AgentAuthError,
    AgentNotInstalledError,
    AgentTimeoutError,
    AgentToolError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ok(stdout: str) -> tuple[str, list[Path], list[str] | None]:
    return "summary-text", [Path("a.py")], None


def _parse_with_questions(stdout: str) -> tuple[str, list[Path], list[str] | None]:
    return "s", [], ["q1?"]


def _done(stdout="", stderr="", rc=0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["fake"], rc, stdout, stderr)


RUN = "ai_agents._subprocess._run_or_raise"

# ---------------------------------------------------------------------------
# CHAT_PREFIX sanity
# ---------------------------------------------------------------------------

def test_chat_prefix_instructs_text_only():
    assert "no" in CHAT_PREFIX.lower() and "text only" in CHAT_PREFIX.lower()


# ---------------------------------------------------------------------------
# invoke_cli — success paths
# ---------------------------------------------------------------------------

@patch(RUN)
def test_success_builds_agent_result(mock_run, tmp_path):
    mock_run.return_value = _done(stdout='{"summary": "done"}')
    result = invoke_cli(
        cmd=["fake", "arg"], cwd=tmp_path, timeout_s=30,
        binary="fake", auth_markers=(), auth_error_msg="no auth",
        parse_result=_parse_ok,
    )
    assert result.success is True
    assert result.summary == "summary-text"
    assert result.files_changed == [Path("a.py")]
    assert result.cost_usd is None
    assert result.duration_s >= 0


@patch(RUN)
def test_success_with_cost_parser(mock_run, tmp_path):
    mock_run.return_value = _done(stdout="whatever")
    result = invoke_cli(
        cmd=["fake"], cwd=tmp_path, timeout_s=10,
        binary="fake", auth_markers=(), auth_error_msg="no",
        parse_result=_parse_ok, cost_parser=lambda _: 0.42,
    )
    assert result.cost_usd == 0.42


@patch(RUN)
def test_success_passes_questions_through(mock_run, tmp_path):
    mock_run.return_value = _done()
    result = invoke_cli(
        cmd=["fake"], cwd=tmp_path, timeout_s=5,
        binary="fake", auth_markers=(), auth_error_msg="",
        parse_result=_parse_with_questions,
    )
    assert result.questions == ["q1?"]


# ---------------------------------------------------------------------------
# invoke_cli — failure paths (non-zero exit via mocked _run_or_raise)
# ---------------------------------------------------------------------------

@patch(RUN)
def test_nonzero_exit_with_auth_marker_raises_auth_error(mock_run, tmp_path):
    mock_run.return_value = _done(stderr="Error: 401 Unauthorized", rc=1)
    with pytest.raises(AgentAuthError) as exc_info:
        invoke_cli(
            cmd=["x"], cwd=tmp_path, timeout_s=1,
            binary="x", auth_markers=("401", "unauthorized"),
            auth_error_msg="run `x login` first",
            parse_result=_parse_ok,
        )
    assert "login" in str(exc_info.value)


@patch(RUN)
def test_nonzero_exit_without_auth_marker_raises_tool_error(mock_run, tmp_path):
    mock_run.return_value = _done(stdout="oops", stderr="some runtime problem", rc=2)
    with pytest.raises(AgentToolError) as exc_info:
        invoke_cli(
            cmd=["x"], cwd=tmp_path, timeout_s=1,
            binary="x", auth_markers=("401",), auth_error_msg="",
            parse_result=_parse_ok,
        )
    assert "exit 2" in str(exc_info.value)


@patch(RUN)
def test_auth_markers_ignored_on_success(mock_run, tmp_path):
    mock_run.return_value = _done(stdout="The answer discusses 401 unauthorized errors")
    result = invoke_cli(
        cmd=["x"], cwd=tmp_path, timeout_s=1,
        binary="x", auth_markers=("401", "unauthorized"),
        auth_error_msg="should not fire", parse_result=_parse_ok,
    )
    assert result.success is True


@patch(RUN)
def test_tool_error_suffix_appended_to_message(mock_run, tmp_path):
    mock_run.return_value = _done(rc=3)
    with pytest.raises(AgentToolError) as exc_info:
        invoke_cli(
            cmd=["x"], cwd=tmp_path, timeout_s=1,
            binary="x", auth_markers=(), auth_error_msg="",
            parse_result=_parse_ok, tool_error_suffix=" (model=foo/bar)",
        )
    assert "exit 3 (model=foo/bar)" in str(exc_info.value)


@patch(RUN)
def test_context_extra_merged_into_exception_context(mock_run, tmp_path):
    mock_run.return_value = _done(stderr="generic failure", rc=1)
    with pytest.raises(AgentToolError) as exc_info:
        invoke_cli(
            cmd=["x"], cwd=tmp_path, timeout_s=1,
            binary="x", auth_markers=(), auth_error_msg="",
            parse_result=_parse_ok, context_extra={"model": "openrouter/xyz"},
        )
    assert exc_info.value.context.get("model") == "openrouter/xyz"


@patch(RUN)
def test_context_extra_merged_on_timeout(mock_run, tmp_path):
    mock_run.side_effect = AgentTimeoutError(
        "x produced no output for 2s", context={"cmd": ["x", "y"], "model": "m"},
    )
    with pytest.raises(AgentTimeoutError) as exc_info:
        invoke_cli(
            cmd=["x", "y"], cwd=tmp_path, timeout_s=2,
            binary="x", auth_markers=(), auth_error_msg="",
            parse_result=_parse_ok, context_extra={"model": "m"},
        )
    assert exc_info.value.context.get("model") == "m"


@patch(RUN)
def test_context_extra_cannot_override_stdout_stderr_tails(mock_run, tmp_path):
    mock_run.return_value = _done(stdout="real-stdout", stderr="real-stderr", rc=2)
    with pytest.raises(AgentToolError) as exc_info:
        invoke_cli(
            cmd=["real"], cwd=tmp_path, timeout_s=1,
            binary="real", auth_markers=(), auth_error_msg="",
            parse_result=_parse_ok,
            context_extra={"stdout_tail": "LIE", "stderr_tail": "LIE", "model": "m"},
        )
    assert exc_info.value.context["stdout_tail"] == "real-stdout"
    assert exc_info.value.context["stderr_tail"] == "real-stderr"
    assert exc_info.value.context["model"] == "m"


@patch(RUN)
def test_context_extra_cannot_override_stderr_tail_on_auth_error(mock_run, tmp_path):
    mock_run.return_value = _done(stderr="401 unauthorized", rc=1)
    with pytest.raises(AgentAuthError) as exc_info:
        invoke_cli(
            cmd=["x"], cwd=tmp_path, timeout_s=1,
            binary="x", auth_markers=("401",), auth_error_msg="login",
            parse_result=_parse_ok,
            context_extra={"stderr_tail": "LIE", "model": "m"},
        )
    assert exc_info.value.context["stderr_tail"] == "401 unauthorized"
    assert exc_info.value.context["model"] == "m"


# ---------------------------------------------------------------------------
# invoke_cli — log warnings
# ---------------------------------------------------------------------------

@patch(RUN)
def test_tool_error_path_emits_warning_log(mock_run, tmp_path, caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="ai_agents._subprocess")
    mock_run.return_value = _done(stderr="boom", rc=5)
    with pytest.raises(AgentToolError):
        invoke_cli(
            cmd=["x"], cwd=tmp_path, timeout_s=1,
            binary="x", auth_markers=(), auth_error_msg="",
            parse_result=_parse_ok,
        )
    assert any("exit 5" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# _run_or_raise — real subprocesses
# ---------------------------------------------------------------------------

def test_run_or_raise_success_captures_output(tmp_path):
    result = _run_or_raise(
        ["python3", "-c", "print('hello')"], tmp_path, 10, "py", {},
    )
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_run_or_raise_binary_not_found_raises(tmp_path):
    with pytest.raises(AgentNotInstalledError) as exc_info:
        _run_or_raise(["__no_such_bin_xyz__"], tmp_path, 5, "nope", {})
    assert exc_info.value.context["cmd"] == "__no_such_bin_xyz__"


def test_run_or_raise_cmd_wins_over_context_extra_on_not_found(tmp_path):
    with pytest.raises(AgentNotInstalledError) as exc_info:
        _run_or_raise(["__no_such_bin__"], tmp_path, 5, "nope", {"cmd": "LIE", "model": "m"})
    assert exc_info.value.context["cmd"] == "__no_such_bin__"
    assert exc_info.value.context["model"] == "m"


def test_run_or_raise_not_found_emits_warning_log(tmp_path, caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="ai_agents._subprocess")
    with pytest.raises(AgentNotInstalledError):
        _run_or_raise(["__absent__"], tmp_path, 1, "__absent__", {})
    assert any("not found" in rec.getMessage() for rec in caplog.records)


def test_run_or_raise_idle_timeout_kills_and_raises(tmp_path):
    with pytest.raises(AgentTimeoutError) as exc_info:
        _run_or_raise(
            ["python3", "-c", "import time; time.sleep(100)"],
            tmp_path, 1, "py", {},
        )
    assert "no output for 1s" in str(exc_info.value)


def test_run_or_raise_cmd_wins_over_context_extra_on_timeout(tmp_path):
    with pytest.raises(AgentTimeoutError) as exc_info:
        _run_or_raise(
            ["python3", "-c", "import time; time.sleep(100)"],
            tmp_path, 1, "py", {"cmd": "LIE"},
        )
    assert exc_info.value.context["cmd"] == ["python3", "-c"]
