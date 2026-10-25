"""Unit tests for ai_agents/registry.py — YAML+env loading, chain parsing, healthchecks."""
from pathlib import Path

import pytest
import yaml

from ai_agents.errors import ConfigError
from ai_agents.codex_agent import CodexAgent
from ai_agents.registry import AgentRegistry


MINIMAL_YAML = {
    "agents": {
        "codex": {"class": "CodexAgent", "cost_tier": "free"},
        "gemini": {"class": "GeminiAgent", "cost_tier": "free"},
        "claude": {"class": "OpenCodeAgent", "model": "anthropic/x", "cost_tier": "high"},
    },
    "coding": {"priority": ["codex", "gemini", "claude"]},
}


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "agents.yml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_load_basic_registry(tmp_path):
    yml = _write_yaml(tmp_path, MINIMAL_YAML)
    reg = AgentRegistry.load(yml, env={})
    assert {a.name for a in reg.coding_chain()} == {"codex", "gemini", "claude"}


def test_missing_coding_priority_raises_config_error(tmp_path):
    data = {"agents": MINIMAL_YAML["agents"]}
    yml = _write_yaml(tmp_path, data)
    with pytest.raises(ConfigError):
        AgentRegistry.load(yml, env={})


def test_unknown_agent_in_priority_raises(tmp_path):
    data = dict(MINIMAL_YAML)
    data["coding"] = {"priority": ["codex", "ghost"]}
    yml = _write_yaml(tmp_path, data)
    with pytest.raises(ConfigError):
        AgentRegistry.load(yml, env={})


def test_env_override_coding_priority(tmp_path):
    yml = _write_yaml(tmp_path, MINIMAL_YAML)
    reg = AgentRegistry.load(yml, env={"AI_CODING_PRIORITY": "gemini,codex"})
    assert [a.name for a in reg.coding_chain()] == ["gemini", "codex"]


def test_paid_before_free_emits_warning(tmp_path, caplog):
    data = dict(MINIMAL_YAML)
    data["coding"] = {"priority": ["claude", "codex"]}  # paid first
    yml = _write_yaml(tmp_path, data)
    with caplog.at_level("WARNING"):
        AgentRegistry.load(yml, env={})
    assert any("paid" in r.message.lower() and "above" in r.message.lower() for r in caplog.records)


def test_build_structured_llm_from_priority(tmp_path):
    data = dict(MINIMAL_YAML)
    data["structured_llm"] = {"priority": ["codex", "litellm:openai/gpt-4o-mini"]}
    yml = _write_yaml(tmp_path, data)
    reg = AgentRegistry.load(yml, env={})
    sllm = reg.build_structured_llm()
    assert sllm is not None


def test_default_structured_agent_is_first_free(tmp_path):
    yml = _write_yaml(tmp_path, MINIMAL_YAML)
    reg = AgentRegistry.load(yml, env={})
    assert reg.default_structured_agent().name == "codex"


def test_codex_defaults_are_loaded_when_yaml_omits_model(tmp_path):
    yml = _write_yaml(tmp_path, MINIMAL_YAML)
    reg = AgentRegistry.load(yml, env={})
    agent = reg.get("codex")
    assert isinstance(agent, CodexAgent)
    assert agent.model == "gpt-5.5"
    assert agent.reasoning_effort == "xhigh"


def test_codex_model_and_effort_can_come_from_yaml(tmp_path):
    data = dict(MINIMAL_YAML)
    data["agents"] = {
        **MINIMAL_YAML["agents"],
        "codex": {
            "class": "CodexAgent",
            "model": "gpt-yaml",
            "reasoning_effort": "medium",
            "cost_tier": "free",
        },
    }
    yml = _write_yaml(tmp_path, data)
    agent = AgentRegistry.load(yml, env={}).get("codex")
    assert isinstance(agent, CodexAgent)
    assert agent.model == "gpt-yaml"
    assert agent.reasoning_effort == "medium"


def test_codex_model_and_effort_env_override_yaml(tmp_path):
    data = dict(MINIMAL_YAML)
    data["agents"] = {
        **MINIMAL_YAML["agents"],
        "codex": {
            "class": "CodexAgent",
            "model": "gpt-yaml",
            "reasoning_effort": "medium",
            "cost_tier": "free",
        },
    }
    yml = _write_yaml(tmp_path, data)
    env = {"CODEX_MODEL": "gpt-env", "CODEX_REASONING_EFFORT": "high"}
    agent = AgentRegistry.load(yml, env=env).get("codex")
    assert isinstance(agent, CodexAgent)
    assert agent.model == "gpt-env"
    assert agent.reasoning_effort == "high"


def test_invalid_codex_reasoning_effort_raises_config_error(tmp_path):
    data = dict(MINIMAL_YAML)
    data["agents"] = {
        **MINIMAL_YAML["agents"],
        "codex": {"class": "CodexAgent", "reasoning_effort": "max", "cost_tier": "free"},
    }
    yml = _write_yaml(tmp_path, data)
    with pytest.raises(ConfigError, match="reasoning_effort"):
        AgentRegistry.load(yml, env={})


def test_get_returns_agent_for_known_name(tmp_path):
    yml = _write_yaml(tmp_path, MINIMAL_YAML)
    reg = AgentRegistry.load(yml, env={})
    assert reg.get("codex").name == "codex"


def test_get_raises_for_unknown_name(tmp_path):
    yml = _write_yaml(tmp_path, MINIMAL_YAML)
    reg = AgentRegistry.load(yml, env={})
    with pytest.raises(ConfigError, match="No agent named"):
        reg.get("ghost")


def test_default_structured_agent_raises_when_all_coding_paid(tmp_path):
    data = {
        "agents": {
            "claude": {"class": "OpenCodeAgent", "model": "anthropic/x", "cost_tier": "high"},
            "openrouter": {"class": "OpenCodeAgent", "model": "openrouter/y", "cost_tier": "medium"},
        },
        "coding": {"priority": ["claude", "openrouter"]},
    }
    yml = _write_yaml(tmp_path, data)
    reg = AgentRegistry.load(yml, env={})
    with pytest.raises(ConfigError, match="free-tier"):
        reg.default_structured_agent()


def test_build_structured_llm_falls_back_to_coding_priority_when_empty(tmp_path):
    # No structured_llm block at all — registry should fall back to coding chain.
    yml = _write_yaml(tmp_path, MINIMAL_YAML)
    reg = AgentRegistry.load(yml, env={})
    sllm = reg.build_structured_llm()
    assert sllm is not None  # ChainedStructuredLLM wrapping 3 agents


def test_malformed_yaml_raises_config_error(tmp_path):
    p = tmp_path / "empty.yml"
    p.write_text("")  # yaml.safe_load("") returns None
    with pytest.raises(ConfigError, match="empty or not a mapping"):
        AgentRegistry.load(p, env={})


def test_opencode_missing_model_raises_config_error(tmp_path):
    data = {
        "agents": {"broken": {"class": "OpenCodeAgent", "cost_tier": "high"}},
        "coding": {"priority": ["broken"]},
    }
    yml = _write_yaml(tmp_path, data)
    with pytest.raises(ConfigError, match="missing required key"):
        AgentRegistry.load(yml, env={})
