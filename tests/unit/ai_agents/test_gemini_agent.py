"""Unit tests for ai_agents/gemini_agent.py — command construction + invocation contract."""
from pathlib import Path
from unittest.mock import patch

from ai_agents.base import AgentResult, AgentTask
from ai_agents.gemini_agent import GeminiAgent


def test_gemini_agent_name_and_cost_tier():
    agent = GeminiAgent()
    assert agent.name == "gemini"
    assert agent.cost_tier == "free"


def test_run_cmd_is_list_not_shell():
    agent = GeminiAgent()
    cmd = agent._build_run_cmd(AgentTask(prompt="ok", cwd=Path("/tmp")))
    assert isinstance(cmd, list)
    assert cmd[0] == "gemini"
    assert "ok" in cmd


def test_run_cmd_enables_yolo_for_headless_tool_use():
    """Headless runs need --approval-mode yolo or tools like google_web_search
    are blocked on the approval prompt. See gemini_agent.py:_build_run_cmd."""
    agent = GeminiAgent()
    cmd = agent._build_run_cmd(AgentTask(prompt="research X", cwd=Path("/tmp")))
    assert "--approval-mode" in cmd
    idx = cmd.index("--approval-mode")
    assert cmd[idx + 1] == "yolo"


def test_chat_cmd_suppresses_tools():
    agent = GeminiAgent()
    cmd = agent._build_chat_cmd("classify")
    joined = " ".join(cmd)
    suppression = ("--approval-mode=never", "--no-tools", "--read-only", "--sandbox=read-only")
    assert any(f in joined for f in suppression) or "no tools" in cmd[-1].lower() \
        or "text only" in cmd[-1].lower()


@patch("ai_agents.gemini_agent.invoke_cli")
def test_run_passes_cwd_and_timeout(mock_invoke, tmp_path):
    mock_invoke.return_value = AgentResult(True, "", [], "", None, 0.1)
    agent = GeminiAgent()
    agent.run(AgentTask(prompt="p", cwd=tmp_path, timeout_s=30))
    _, kwargs = mock_invoke.call_args
    assert kwargs["cwd"] == tmp_path
    assert kwargs["timeout_s"] == 30


def test_healthcheck_returns_bool():
    assert isinstance(GeminiAgent().healthcheck(), bool)


def test_parse_stdout_handles_json_or_jsonl():
    """Whatever gemini emits, parser shouldn't crash and should return a summary."""
    from ai_agents.gemini_agent import GeminiAgent
    # Single-JSON shape
    s1, f1, q1 = GeminiAgent._parse_stdout('{"summary": "ok", "files_changed": []}')
    assert "ok" in s1 or s1 == "ok"
    # JSONL shape (if gemini emits one)
    s2, f2, q2 = GeminiAgent._parse_stdout('{"type":"msg","text":"hello"}\n{"type":"done"}')
    assert isinstance(s2, str) and len(s2) > 0
    # Plain text fallback
    s3, f3, q3 = GeminiAgent._parse_stdout("plain response")
    assert s3 == "plain response"


# --- coverage-closure tests ---------------------------------------------


def test_chat_returns_parsed_summary():
    """chat() strips gemini's session_id/stats chrome via _parse_stdout."""
    with patch.object(
        GeminiAgent,
        "_invoke",
        return_value=AgentResult(True, "yes", [], "raw gemini output", None, 0.1),
    ):
        out = GeminiAgent().chat("question?")
    assert out == "yes"


def test_chat_falls_back_to_output_when_summary_matches_prefix():
    """When parser returns stdout[:200] as summary (no known keys), chat returns raw."""
    with patch.object(
        GeminiAgent,
        "_invoke",
        return_value=AgentResult(True, "short plain text", [], "short plain text", None, 0.1),
    ):
        out = GeminiAgent().chat("hi")
    assert out == "short plain text"


@patch("ai_agents.gemini_agent.subprocess.run")
def test_healthcheck_returns_false_when_binary_missing(mock_run):
    mock_run.side_effect = FileNotFoundError("gemini not installed")
    assert GeminiAgent().healthcheck() is False


@patch("ai_agents.gemini_agent.subprocess.run")
def test_healthcheck_returns_false_on_nonzero_returncode(mock_run):
    mock_run.return_value.returncode = 1
    assert GeminiAgent().healthcheck() is False


def test_parse_jsonl_two_events_with_files_and_questions():
    """JSONL path collects files_changed + questions across events."""
    from ai_agents.gemini_agent import GeminiAgent
    lines = [
        '{"text": "line1"}',
        '{"text": "line2", "files_changed": ["a.py"], "questions": ["q?"]}',
    ]
    summary, files, questions = GeminiAgent._parse_jsonl(lines)
    assert summary == "line2"
    assert files == [Path("a.py")]
    assert questions == ["q?"]


def test_parse_single_json_with_files_and_questions():
    """Single-JSON path handles files_changed + questions."""
    from ai_agents.gemini_agent import GeminiAgent
    stdout = '{"response": "done", "files_changed": ["x.py"], "questions": ["why?"]}'
    result = GeminiAgent._parse_single_json(stdout)
    assert result is not None
    summary, files, questions = result
    assert summary == "done"
    assert files == [Path("x.py")]
    assert questions == ["why?"]


def test_parse_single_json_returns_none_for_non_dict():
    """Single-JSON path returns None when parsed JSON is not a dict."""
    from ai_agents.gemini_agent import GeminiAgent
    assert GeminiAgent._parse_single_json("[1, 2, 3]") is None
