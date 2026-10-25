"""Unit tests for ai_agents/opencode_agent.py - command construction + cost parsing."""
from pathlib import Path
from unittest.mock import patch

from ai_agents.base import AgentResult, AgentTask
from ai_agents.opencode_agent import OpenCodeAgent, _parse_opencode_cost


def test_opencode_agent_accepts_model_and_cost_tier():
    agent = OpenCodeAgent(name="claude", model="anthropic/claude-opus-4-7", cost_tier="high")
    assert agent.name == "claude"
    assert agent.model == "anthropic/claude-opus-4-7"
    assert agent.cost_tier == "high"


def test_run_cmd_includes_model_flag():
    agent = OpenCodeAgent(name="openrouter", model="openrouter/x/y", cost_tier="medium")
    cmd = agent._build_run_cmd(AgentTask(prompt="hi", cwd=Path("/tmp")))
    assert cmd[0] == "opencode"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "openrouter/x/y"


def test_parse_opencode_cost_reads_top_level_cost():
    assert _parse_opencode_cost('{"cost": 0.12}') == 0.12


def test_parse_opencode_cost_reads_usage_total_cost():
    assert _parse_opencode_cost('{"usage": {"total_cost": 0.05}}') == 0.05


def test_parse_opencode_cost_reads_usage_cost_usd():
    assert _parse_opencode_cost('{"usage": {"cost_usd": 0.07}}') == 0.07


def test_parse_opencode_cost_returns_none_when_absent():
    assert _parse_opencode_cost('{"other": 1}') is None
    assert _parse_opencode_cost("not json") is None


@patch("ai_agents.opencode_agent.invoke_cli")
def test_run_parses_cost_from_stdout(mock_invoke, tmp_path):
    stdout = '{"summary": "done", "cost": 0.03, "files_changed": ["a.py"]}'

    def fake_invoke(**kwargs):
        summary, files, questions = kwargs["parse_result"](stdout)
        cost = kwargs["cost_parser"](stdout)
        return AgentResult(True, summary, files, stdout, cost, 0.1, questions=questions)

    mock_invoke.side_effect = fake_invoke
    agent = OpenCodeAgent(name="openrouter", model="openrouter/x", cost_tier="medium")
    result = agent.run(AgentTask(prompt="p", cwd=tmp_path, timeout_s=30))
    assert result.cost_usd == 0.03
    assert result.files_changed == [Path("a.py")]


def test_healthcheck_returns_bool():
    agent = OpenCodeAgent(name="openrouter", model="x/y", cost_tier="medium")
    assert isinstance(agent.healthcheck(), bool)


# --- coverage-closure tests ---------------------------------------------


def test_chat_returns_parsed_summary():
    """chat() strips chrome via _parse_opencode_summary."""
    agent = OpenCodeAgent(name="x", model="x/y", cost_tier="low")
    with patch.object(
        OpenCodeAgent,
        "_invoke",
        return_value=AgentResult(True, "done", [], "raw opencode output", 0.01, 0.1),
    ):
        assert agent.chat("hi") == "done"


def test_chat_falls_back_to_output_for_plain_text():
    agent = OpenCodeAgent(name="x", model="x/y", cost_tier="low")
    with patch.object(
        OpenCodeAgent,
        "_invoke",
        return_value=AgentResult(True, "no json here", [], "no json here", None, 0.1),
    ):
        assert agent.chat("hi") == "no json here"


def test_build_chat_cmd_includes_model_and_prefix():
    agent = OpenCodeAgent(name="x", model="x/y", cost_tier="low")
    cmd = agent._build_chat_cmd("question")
    assert cmd[0] == "opencode"
    assert "--model" in cmd
    assert "text only" in cmd[-1].lower()


@patch("ai_agents.opencode_agent.subprocess.run")
def test_healthcheck_returns_false_when_binary_missing(mock_run):
    mock_run.side_effect = FileNotFoundError("opencode not installed")
    agent = OpenCodeAgent(name="x", model="x/y", cost_tier="low")
    assert agent.healthcheck() is False


def test_parse_opencode_cost_pretty_printed_json():
    """Multi-line pretty-printed JSON (no line is individual valid JSON) parses as single doc."""
    from ai_agents.opencode_agent import _parse_opencode_cost
    stdout = '{\n  "cost": 0.5,\n  "other": "thing"\n}'
    assert _parse_opencode_cost(stdout) == 0.5


def test_parse_opencode_cost_falls_through_when_jsonl_parsed_but_no_cost():
    """When per-line parse succeeds but no cost key present, don't re-parse as single doc."""
    from ai_agents.opencode_agent import _parse_opencode_cost
    stdout = '{"other": 1}\n{"more": 2}'
    assert _parse_opencode_cost(stdout) is None


def test_parse_opencode_summary_single_json_with_item_text():
    """Single-JSON fallback handles pretty-printed doc with all fields."""
    from ai_agents.opencode_agent import _parse_opencode_summary
    stdout = '{\n  "response": "hello",\n  "files_changed": ["a.py"],\n  "questions": ["why?"]\n}'
    summary, files, questions = _parse_opencode_summary(stdout)
    assert summary == "hello"
    assert files == [Path("a.py")]
    assert questions == ["why?"]


def test_parse_opencode_summary_jsonl_with_item_text():
    """item.text inside a JSONL event is collected as a fallback."""
    from ai_agents.opencode_agent import _parse_opencode_summary
    stdout = (
        '{"other": 1}\n'
        '{"item": {"text": "from item"}}\n'
    )
    summary, _, _ = _parse_opencode_summary(stdout)
    assert summary == "from item"


def test_parse_opencode_summary_non_dict_json_falls_back():
    """If single-doc parse yields a non-dict (list/number), fall back to plain text."""
    from ai_agents.opencode_agent import _parse_opencode_summary
    stdout = "[1, 2, 3]"
    summary, files, questions = _parse_opencode_summary(stdout)
    assert summary == stdout[:200]
    assert files == []
    assert questions is None
