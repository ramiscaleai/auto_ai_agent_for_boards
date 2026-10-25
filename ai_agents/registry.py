"""AgentRegistry — load agents.yml + .env overrides, build priority chains.

See spec section `registry.py`. Fail-fast on config errors; WARNING (not crash)
when all coding agents fail healthcheck — structured-only may still be useful.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Mapping

import yaml

from ai_agents.base import AIAgent
from ai_agents.codex_agent import (
    DEFAULT_CODEX_MODEL,
    DEFAULT_CODEX_REASONING_EFFORT,
    CodexAgent,
)
from ai_agents.errors import ConfigError
from ai_agents.gemini_agent import GeminiAgent
from ai_agents.opencode_agent import OpenCodeAgent
from ai_agents.structured_llm import (
    AgentStructuredLLM,
    ChainedStructuredLLM,
    LiteLLMStructuredLLM,
    StructuredLLM,
)

_log = logging.getLogger("ai_agents.registry")

_AGENT_CLASSES: dict[str, type] = {
    "CodexAgent": CodexAgent,
    "GeminiAgent": GeminiAgent,
    "OpenCodeAgent": OpenCodeAgent,
}


class AgentRegistry:
    def __init__(
        self,
        agents: dict[str, AIAgent],
        coding_priority: list[str],
        structured_priority: list[str],
    ) -> None:
        self._agents = agents
        self._coding_priority = coding_priority
        self._structured_priority = structured_priority

    # --- construction ----------------------------------------------------

    @classmethod
    def load(cls, yaml_path: Path, env: Mapping[str, str]) -> "AgentRegistry":
        data = yaml.safe_load(yaml_path.read_text())
        if not isinstance(data, dict):
            raise ConfigError("agents.yml is empty or not a mapping")
        agents = _instantiate_agents(data.get("agents", {}), env)
        coding_priority = _resolve_priority(
            data.get("coding", {}).get("priority"), env.get("AI_CODING_PRIORITY"), agents, "coding",
        )
        structured_priority = _resolve_priority(
            (data.get("structured_llm") or {}).get("priority"),
            env.get("AI_STRUCTURED_PRIORITY"),
            agents,
            "structured_llm",
            allow_litellm=True,
            allow_empty=True,
        )
        reg = cls(agents, coding_priority, structured_priority)
        reg._run_healthchecks()
        reg._warn_if_paid_before_free()
        return reg

    # --- lookups ---------------------------------------------------------

    def get(self, name: str) -> AIAgent:
        if name not in self._agents:
            raise ConfigError(f"No agent named {name!r} in registry", context={"available": list(self._agents)})
        return self._agents[name]

    def coding_chain(self) -> list[AIAgent]:
        return [self._agents[n] for n in self._coding_priority]

    def default_structured_agent(self) -> AIAgent:
        for name in self._coding_priority:
            agent = self._agents[name]
            if agent.cost_tier == "free":
                return agent
        raise ConfigError("No free-tier agent available for structured LLM default")

    def build_structured_llm(self) -> StructuredLLM:
        priority = self._structured_priority or self._coding_priority
        providers: list[StructuredLLM] = []
        for entry in priority:
            if entry.startswith("litellm:"):
                model = entry[len("litellm:") :]
                providers.append(LiteLLMStructuredLLM(model=model))
            else:
                providers.append(AgentStructuredLLM(self._agents[entry]))
        return ChainedStructuredLLM(providers)

    # --- helpers ---------------------------------------------------------

    def _run_healthchecks(self) -> None:
        results = {n: a.healthcheck() for n, a in self._agents.items()}
        up = sorted(n for n, ok in results.items() if ok)
        down = sorted(n for n, ok in results.items() if not ok)
        _log.info("agents_up=%s agents_down=%s", up, down)
        if not any(results[n] for n in self._coding_priority):
            _log.warning("No healthy agent in coding chain; structured-only may still work.")

    def _warn_if_paid_before_free(self) -> None:
        for chain_name, chain in (("coding", self._coding_priority), ("structured_llm", self._structured_priority)):
            seen_paid = None
            for entry in chain:
                if entry.startswith("litellm:"):
                    seen_paid = entry
                    continue
                agent = self._agents.get(entry)
                if agent is None:
                    continue
                if agent.cost_tier != "free":
                    seen_paid = entry
                elif seen_paid is not None:
                    _log.warning(
                        "%s.priority places paid %r above free %r — intentional?",
                        chain_name, seen_paid, entry,
                    )
                    break


def _instantiate_agents(section: dict, env: Mapping[str, str]) -> dict[str, AIAgent]:
    out: dict[str, AIAgent] = {}
    for name, cfg in section.items():
        cls_name = cfg.get("class")
        if cls_name not in _AGENT_CLASSES:
            raise ConfigError(f"Unknown agent class {cls_name!r} for {name!r}")
        cls = _AGENT_CLASSES[cls_name]
        if cls is OpenCodeAgent:
            agent = _instantiate_opencode_agent(name, cfg)
        elif cls is CodexAgent:
            agent = _instantiate_codex_agent(name, cfg, env)
        else:
            agent = cls()
            agent.name = name  # type: ignore[attr-defined]
            agent.cost_tier = cfg.get("cost_tier", agent.cost_tier)  # type: ignore[attr-defined]
        out[name] = agent
    return out


def _instantiate_codex_agent(
    name: str, cfg: dict, env: Mapping[str, str],
) -> CodexAgent:
    model = env.get("CODEX_MODEL") or cfg.get("model", DEFAULT_CODEX_MODEL)
    effort = env.get("CODEX_REASONING_EFFORT") or cfg.get(
        "reasoning_effort", DEFAULT_CODEX_REASONING_EFFORT,
    )
    try:
        agent = CodexAgent(model=model, reasoning_effort=effort)
    except ValueError as exc:
        raise ConfigError(str(exc), context={"name": name}) from exc
    agent.name = name
    agent.cost_tier = cfg.get("cost_tier", agent.cost_tier)
    return agent


def _instantiate_opencode_agent(name: str, cfg: dict) -> OpenCodeAgent:
    try:
        return OpenCodeAgent(name=name, model=cfg["model"], cost_tier=cfg["cost_tier"])
    except KeyError as exc:
        raise ConfigError(
            f"OpenCodeAgent {name!r} missing required key {exc.args[0]!r}",
            context={"name": name, "cfg_keys": sorted(cfg)},
        ) from exc


def _resolve_priority(
    yaml_list: list[str] | None,
    env_override: str | None,
    agents: dict[str, AIAgent],
    label: str,
    allow_litellm: bool = False,
    allow_empty: bool = False,
) -> list[str]:
    raw = env_override.split(",") if env_override else yaml_list
    if raw is None:
        if allow_empty:
            return []
        raise ConfigError(f"Missing required {label}.priority in agents.yml and no env override")
    cleaned = [entry.strip() for entry in raw if entry.strip()]
    for entry in cleaned:
        if entry.startswith("litellm:"):
            if not allow_litellm:
                raise ConfigError(f"'litellm:' entries are not allowed in {label}.priority")
            continue
        if entry not in agents:
            raise ConfigError(
                f"{label}.priority references unknown agent {entry!r}",
                context={"known": sorted(agents)},
            )
    return cleaned
