"""LLM-powered branch name generator.

Format: task/<1-3 core words>[-<0-3 extra words>]-<4 hex suffix of task id>
Decision delegated to the configured structured-LLM chain (same priority order as task execution).
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel, field_validator

log = logging.getLogger(__name__)

_SAFE = re.compile(r"[^a-z0-9]+")


class _BranchSlug(BaseModel):
    words: list[str]  # 1-6 lowercase words; extra chars stripped downstream

    @field_validator("words")
    @classmethod
    def _validate(cls, v: list[str]) -> list[str]:
        if not 1 <= len(v) <= 6:
            raise ValueError("words must have 1-6 entries")
        return [w.lower().strip() for w in v if w.strip()]


_PROMPT = """\
You are naming a git branch for a development task.

Rules:
- Pick 1-3 words that capture the core subject of the task title (mandatory).
- Add 0-3 extra words ONLY if they add distinct meaning not already in the first 1-3 words.
- Each word must be lowercase letters and digits only (no punctuation, no articles like 'a/an/the').
- Aim for the shortest slug that still conveys full meaning.
- Return ONLY the JSON object with key "words" containing the list of words.

Task title: {title}
"""


class BranchNamer:
    """Generates a branch name slug via the structured-LLM chain."""

    def __init__(self, structured_llm: object) -> None:
        self._llm = structured_llm

    def name(self, task_title: str, task_id: str) -> str:
        suffix = _hex_suffix(task_id)
        try:
            result: _BranchSlug = self._llm.ask(
                _PROMPT.format(title=task_title.strip()),
                _BranchSlug,
            )
            words = [_SAFE.sub("", w) for w in result.words if _SAFE.sub("", w)]
            if not words:
                raise ValueError("no usable words")
            slug = "-".join(words[:6])
        except Exception as exc:  # noqa: BLE001
            log.warning("BranchNamer LLM call failed (%s) — falling back to task id", exc)
            slug = _fallback_slug(task_title)

        return f"task/{slug}-{suffix}"


def _hex_suffix(task_id: str) -> str:
    """Return last 4 hex characters of task_id, or a 4-char fallback."""
    hex_chars = re.sub(r"[^0-9a-f]", "", task_id.lower())
    return hex_chars[-4:] if len(hex_chars) >= 4 else task_id[-4:].lower()


def _fallback_slug(title: str) -> str:
    words = [_SAFE.sub("", w.lower()) for w in title.split() if _SAFE.sub("", w.lower())]
    return "-".join(words[:3]) if words else "task"
