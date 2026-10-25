"""Detects "seed N backlog tasks" intent from a Trello card.

Why this exists: TaskRunner used to route every card to a coding agent. For
backlog-seeding cards the coding agent has no credentials path to Trello from
inside the target repo worktree, so it quietly writes docs/CSVs and reports
success — a fake-done. This classifier lets TaskRunner branch to a
deterministic seeder instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TOP_N_RE = re.compile(
    r"\btop\s+(\d{1,3})(?:\s+[\w,]+){0,6}?\s+(?:tasks?|items?|cards?)\b",
    re.IGNORECASE,
)
_BACKLOG_HINTS = ("backlog", "to trello", "to do list", "trello card", "most relevant", "most impactful")
_MIN_BACKEND_RE = re.compile(r"(?:at\s+)?least\s+(\d{1,3})\s+(?:for\s+)?backend", re.IGNORECASE)
_MIN_FRONTEND_RE = re.compile(r"(?:at\s+)?least\s+(\d{1,3})\s+(?:for\s+)?frontend", re.IGNORECASE)
_FRONTEND_EXCLUDES_TRELLO = re.compile(r"frontend[^.\n]*not\s+trello|frontend[^.\n]*which\s+is\s+not\s+trello", re.IGNORECASE)


@dataclass(frozen=True)
class SeedIntent:
    count: int
    min_backend: int
    min_frontend: int
    frontend_excludes_trello: bool
    raw_text: str


def parse_seed_intent(title: str, description: str) -> SeedIntent | None:
    combined = f"{title}\n{description or ''}"
    match = _TOP_N_RE.search(combined)
    if not match:
        return None
    if not any(hint in combined.lower() for hint in _BACKLOG_HINTS):
        return None
    count = int(match.group(1))
    if count <= 0 or count > 200:
        return None
    min_backend = _extract_int(_MIN_BACKEND_RE, combined, default=0)
    min_frontend = _extract_int(_MIN_FRONTEND_RE, combined, default=0)
    return SeedIntent(
        count=count,
        min_backend=min_backend,
        min_frontend=min_frontend,
        frontend_excludes_trello=bool(_FRONTEND_EXCLUDES_TRELLO.search(combined)),
        raw_text=combined.strip(),
    )


def _extract_int(pattern: re.Pattern[str], text: str, default: int) -> int:
    m = pattern.search(text)
    return int(m.group(1)) if m else default
