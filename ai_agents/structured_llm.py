"""Structured (JSON-schema) LLM helper.

ABC with three concrete impls:
- AgentStructuredLLM: wraps any AIAgent — free when the agent is subscription-tier.
- LiteLLMStructuredLLM: direct LiteLLM + Instructor call — paid per token.
- ChainedStructuredLLM: tries each provider in priority order.

Used for non-code decisions: task classification, 'am I stuck?', comment drafting.
See spec section `structured_llm.py`.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from ai_agents.base import AIAgent
from ai_agents.errors import AIAgentError, AllAgentsFailedError, StructuredLLMParseError

if TYPE_CHECKING:
    from ai_agents.cost_guard import CostGuard

_log = logging.getLogger("ai_agents.structured_llm")


class StructuredLLM(ABC):
    @abstractmethod
    def ask(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_retries: int = 2,
        chat_timeout_s: int | None = None,
    ) -> BaseModel: ...


class AgentStructuredLLM(StructuredLLM):
    """Delegates to any AIAgent's chat() mode. Free when the agent is subscription-tier."""

    def __init__(self, agent: AIAgent) -> None:
        self._agent = agent

    def ask(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_retries: int = 2,
        chat_timeout_s: int | None = None,
    ) -> BaseModel:
        current = _build_json_prompt(prompt, schema)
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            text = self._agent.chat(current, timeout_s=chat_timeout_s) if chat_timeout_s \
                else self._agent.chat(current)
            cleaned = _strip_fences(text)
            try:
                return schema.model_validate_json(cleaned)
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                last_err = exc
                _log.warning("structured parse failed (attempt %d/%d): %s", attempt + 1, max_retries + 1, exc)
                current = _correction_prompt(prompt, schema, exc)
        raise StructuredLLMParseError(
            f"Parse failed after {max_retries + 1} attempts",
            context={"agent_name": self._agent.name, "last_error": str(last_err)},
        )


class LiteLLMStructuredLLM(StructuredLLM):
    """Direct LiteLLM + Instructor call — paid per token; cost_guard-gated if supplied."""

    def __init__(self, model: str, cost_guard: "CostGuard | None" = None) -> None:
        self._model = model
        # TODO(Task 12): wire cost_guard.charge() around the instructor call in ask().
        self._cost_guard = cost_guard
        # Lazy import keeps litellm out of subscription-only deployments.
        import instructor
        from litellm import completion

        self._instructor = instructor.from_litellm(completion)

    def ask(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_retries: int = 2,
        chat_timeout_s: int | None = None,
    ) -> BaseModel:
        try:
            return self._instructor.chat.completions.create(
                model=self._model,
                response_model=schema,
                messages=[{"role": "user", "content": prompt}],
                max_retries=max_retries,
            )
        except Exception as exc:  # noqa: BLE001 — instructor wraps many underlying errors
            raise StructuredLLMParseError(
                f"LiteLLM structured call failed: {exc}",
                context={"model": self._model},
            ) from exc


class ChainedStructuredLLM(StructuredLLM):
    """Tries each provider in priority order; falls through on failure."""

    def __init__(self, providers: list[StructuredLLM]) -> None:
        if not providers:
            raise ValueError("ChainedStructuredLLM requires at least one provider")
        self._providers = providers

    def ask(
        self,
        prompt: str,
        schema: type[BaseModel],
        max_retries: int = 2,
        chat_timeout_s: int | None = None,
    ) -> BaseModel:
        attempted: list[str] = []
        errors: list[str] = []
        for provider in self._providers:
            label = type(provider).__name__
            attempted.append(label)
            try:
                return provider.ask(
                    prompt, schema, max_retries=max_retries, chat_timeout_s=chat_timeout_s,
                )
            except Exception as exc:  # noqa: BLE001 — providers may raise non-AIAgentError
                errors.append(f"{label}: {type(exc).__name__}: {exc}")
                _log.warning("provider %s failed: %s — trying next", label, exc)
        raise AllAgentsFailedError(
            "All structured-LLM providers failed",
            context={"attempted": attempted, "errors": errors},
        )


def _build_json_prompt(question: str, schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    return (
        f"Respond with ONLY valid JSON matching this schema:\n\n{schema_json}\n\n"
        f"No prose, no code fences, no markdown — only the raw JSON object.\n\n"
        f"Task: {question}"
    )


def _correction_prompt(original: str, schema: type[BaseModel], err: Exception) -> str:
    return (
        f"Your previous response failed validation: {err}\n\n"
        f"Respond again with ONLY a raw JSON object matching this schema:\n"
        f"{json.dumps(schema.model_json_schema(), indent=2)}\n\n"
        f"Task: {original}"
    )


def _strip_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        # ```json ... ```
        s = s.split("\n", 1)[-1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()
