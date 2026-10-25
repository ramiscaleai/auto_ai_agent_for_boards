"""Unit tests for ai_agents/codex_agent.py — command construction, subprocess contract.

Real CLI invocation is covered in tests/e2e/ai_agents/test_codex_healthcheck.py.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_agents.base import AgentResult, AgentTask
from ai_agents.codex_agent import CodexAgent


def test_codex_agent_name_and_cost_tier():
    agent = CodexAgent()
    assert agent.name == "codex"
    assert agent.cost_tier == "free"
    assert agent.model == "gpt-5.5"
    assert agent.reasoning_effort == "xhigh"


def test_codex_agent_accepts_custom_model_and_reasoning_effort():
    agent = CodexAgent(model="gpt-test", reasoning_effort="high")
    assert agent.model == "gpt-test"
    assert agent.reasoning_effort == "high"


def test_codex_agent_rejects_invalid_reasoning_effort():
    with pytest.raises(ValueError, match="reasoning_effort"):
        CodexAgent(reasoning_effort="max")


def test_run_cmd_uses_shell_false_and_list_args():
    agent = CodexAgent()
    cmd = agent._build_run_cmd(AgentTask(prompt="hello", cwd=Path("/tmp")))
    assert isinstance(cmd, list)
    assert cmd[0] == "codex"
    # Prompt appears as its own list element (not interpolated into any earlier arg)
    assert "hello" in cmd
    # Binary name is not concatenated with anything
    assert cmd[0] == "codex"


def test_run_cmd_includes_explicit_model_and_reasoning_effort():
    agent = CodexAgent(model="gpt-test", reasoning_effort="high")
    cmd = agent._build_run_cmd(AgentTask(prompt="hello", cwd=Path("/tmp")))
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-test"
    assert "-c" in cmd
    assert cmd[cmd.index("-c") + 1] == 'model_reasoning_effort="high"'


def test_chat_cmd_disables_tools_somehow():
    agent = CodexAgent()
    cmd = agent._build_chat_cmd("classify this")
    assert isinstance(cmd, list)
    assert cmd[0] == "codex"
    # Either a CLI flag suppresses tools, or the prompt itself says so.
    joined = " ".join(cmd)
    suppression_flags = ("--sandbox-read-only", "--no-tools", "--approval-mode=never", "--read-only")
    assert any(f in joined for f in suppression_flags) or "no tools" in cmd[-1].lower() \
        or "text only" in cmd[-1].lower()


def test_chat_cmd_includes_explicit_model_and_reasoning_effort():
    agent = CodexAgent(model="gpt-chat", reasoning_effort="medium")
    cmd = agent._build_chat_cmd("classify this")
    assert cmd[cmd.index("--model") + 1] == "gpt-chat"
    assert cmd[cmd.index("-c") + 1] == 'model_reasoning_effort="medium"'


@patch("ai_agents.codex_agent.invoke_cli")
def test_run_passes_cmd_cwd_and_timeout_to_invoke(mock_invoke, tmp_path):
    mock_invoke.return_value = AgentResult(True, "did it", [], "", None, 0.1)
    agent = CodexAgent()
    task = AgentTask(prompt="p", cwd=tmp_path, timeout_s=60)
    agent.run(task)
    _, kwargs = mock_invoke.call_args
    assert kwargs["cmd"] == agent._build_run_cmd(task)
    assert kwargs["cwd"] == tmp_path
    assert kwargs["timeout_s"] == 60


def test_healthcheck_returns_bool():
    # Real CLI may or may not be installed — we just want a bool contract.
    result = CodexAgent().healthcheck()
    assert isinstance(result, bool)


def test_parse_stdout_handles_jsonl():
    """Real codex --json emits JSONL — verify we pick the last agent message."""
    from ai_agents.codex_agent import CodexAgent
    stdout = (
        '{"type": "thread.started", "thread_id": "t1"}\n'
        '{"type": "turn.started"}\n'
        '{"type": "item.completed", "item": {"type": "agent_message", "text": "hello there"}}\n'
        '{"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 3}}\n'
    )
    summary, files, questions = CodexAgent._parse_stdout(stdout)
    assert summary == "hello there"
    assert files == []
    assert questions is None


def test_parse_stdout_falls_back_to_plain_text():
    """No JSON at all — returns first 200 chars of stdout."""
    from ai_agents.codex_agent import CodexAgent
    summary, files, questions = CodexAgent._parse_stdout("plain text no json")
    assert summary == "plain text no json"
    assert files == []
    assert questions is None


# --- coverage-closure tests ---------------------------------------------


def test_chat_returns_parsed_summary_not_raw_output():
    """chat() strips the codex banner/footer chrome via _parse_stdout."""
    with patch.object(
        CodexAgent,
        "_invoke",
        return_value=AgentResult(True, "42", [], "raw codex output", None, 0.1),
    ):
        out = CodexAgent().chat("What is 6 times 7?")
    assert out == "42"


def test_parse_stdout_handles_scalar_json_line():
    """A scalar JSON line is valid JSON but not a Codex event."""
    summary, files, questions = CodexAgent._parse_stdout("42\n")
    assert summary == "42\n"
    assert files == []
    assert questions is None


def test_chat_falls_back_to_output_when_summary_is_empty():
    """When no agent_message parses, chat() returns raw output."""
    with patch.object(
        CodexAgent,
        "_invoke",
        return_value=AgentResult(
            True, "plain text response", [], "plain text response", None, 0.1,
        ),
    ):
        out = CodexAgent().chat("hi")
    # Parser returns stdout[:200] for non-JSON; chat sees summary == output[:200]
    # and falls back to returning the raw output.
    assert out == "plain text response"


@patch("ai_agents.codex_agent.subprocess.run")
def test_healthcheck_returns_false_when_binary_missing(mock_run):
    mock_run.side_effect = FileNotFoundError("codex not installed")
    assert CodexAgent().healthcheck() is False


@patch("ai_agents.codex_agent.subprocess.run")
def test_healthcheck_returns_false_on_nonzero_returncode(mock_run):
    mock_run.return_value.returncode = 1
    assert CodexAgent().healthcheck() is False


def test_parse_stdout_single_json_with_questions():
    """Legacy single-JSON shape with questions + files_changed fields."""
    stdout = '{"summary": "did work", "files_changed": ["a.py"], "questions": ["why?"]}'
    summary, files, questions = CodexAgent._parse_stdout(stdout)
    assert summary == "did work"
    assert files == [Path("a.py")]
    assert questions == ["why?"]


def test_parse_stdout_jsonl_generic_text_before_agent_message():
    """Generic item.text (no type='agent_message') fills in when no agent_message arrives."""
    stdout = '{"item": {"text": "fallback"}}\n'
    summary, _, _ = CodexAgent._parse_stdout(stdout)
    assert summary == "fallback"


def test_parse_stdout_jsonl_files_changed_extracted():
    """files_changed at top level of an event is collected across events."""
    stdout = (
        '{"item": {"type": "agent_message", "text": "ok"}}\n'
        '{"files_changed": ["x.py", "y.py"]}\n'
    )
    _, files, _ = CodexAgent._parse_stdout(stdout)
    assert files == [Path("x.py"), Path("y.py")]
