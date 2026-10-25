"""OpenCodeAgent - subprocess wrapper around sst/opencode.

One binary, 75+ providers via `--model <provider>/<model>`. Used for both the
OpenRouter (`openrouter/...`) and Claude API (`anthropic/...`) slots in the
coding chain. Does NOT use Claude Pro/Max subscription - that was removed in
OpenCode v1.3.0 per Anthropic ToS.

Follows the hardening pattern from CodexAgent/GeminiAgent:
- Auth-check gated on non-zero exit (via shared invoke_cli).
- Parser tolerant of JSONL, single-JSON, and plain-text.
- chat() in a tempdir with prompt prefix fallback for tool suppression.

Flag notes (Step 0 probe skipped - `opencode` not installed on this machine).
Defensively supports three cost field shapes so the first real run wins:
- Top-level `{"cost": 0.03}`
- Nested `{"usage": {"total_cost": 0.03}}`
- Nested `{"usage": {"cost_usd": 0.03}}`
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from ai_agents._subprocess import CHAT_PREFIX, invoke_cli
from ai_agents.base import AIAgent, AgentResult, AgentTask

_log = logging.getLogger("ai_agents.opencode")

CostTier = Literal["free", "low", "medium", "high"]

_AUTH_MARKERS = (
    "unauthorized", "401", "403", "invalid api key",
    "not authenticated", "auth required", "missing api key",
)


class OpenCodeAgent(AIAgent):
    """Parameterized opencode wrapper (multiple instances across the chain)."""

    def __init__(self, *, name: str, model: str, cost_tier: CostTier) -> None:
        self.name = name
        self.model = model
        self.cost_tier = cost_tier

    def run(self, task: AgentTask) -> AgentResult:
        return self._invoke(self._build_run_cmd(task), task.cwd, task.timeout_s)

    def chat(self, prompt: str, timeout_s: int = 60) -> str:
        cmd = self._build_chat_cmd(prompt)
        with tempfile.TemporaryDirectory() as tmp:
            result = self._invoke(cmd, Path(tmp), timeout_s)
        if result.summary and result.summary != result.output[:200]:
            return result.summary
        return result.output

    def healthcheck(self) -> bool:
        """Install check only - OpenCode is API-based, credentials live in .env,
        so we can't do a cheap offline auth probe. A bad API key surfaces as
        AgentAuthError at run() time.

        Runs under a throwaway $TMPDIR: opencode (a Bun standalone) extracts its
        embedded native libs there on every launch — even ``--version`` — and
        never cleans up. This probe fires on every poll (every ~5 min), so an
        un-sandboxed run leaked ~288 × 7.8 MB/day into /tmp. The temp dir is
        deleted as soon as the probe returns."""
        try:
            with tempfile.TemporaryDirectory(prefix="opencode-tmp-") as td:
                r = subprocess.run(
                    ["opencode", "--version"], capture_output=True, timeout=10,
                    check=False, env={**os.environ, "TMPDIR": td},
                )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    # --- helpers ---------------------------------------------------------

    def _build_run_cmd(self, task: AgentTask) -> list[str]:
        # `opencode run` is the non-interactive entry; `--format json` asks the
        # CLI for machine-parseable output. Prompt is the final positional arg.
        return [
            "opencode", "run",
            "--model", self.model,
            "--format", "json",
            task.prompt,
        ]

    def _build_chat_cmd(self, prompt: str) -> list[str]:
        # OpenCode has no cross-provider `--no-tools` flag; rely on the same
        # prompt-prefix belt-and-braces approach used by Codex/Gemini.
        return [
            "opencode", "run",
            "--model", self.model,
            "--format", "json",
            f"{CHAT_PREFIX}{prompt}",
        ]

    def _invoke(self, cmd: list[str], cwd: Path, timeout_s: int) -> AgentResult:
        # opencode is a Bun standalone: it extracts its embedded native libs
        # (miniaudio, ~7.8 MB) into $TMPDIR on EVERY launch and never deletes
        # them. Sandbox $TMPDIR to a throwaway dir removed after the call so the
        # extractions can't accumulate (they leaked ~288/day into the shared
        # agent temp before this fix — see CHANGELOG 2026-06-17).
        with tempfile.TemporaryDirectory(prefix="opencode-tmp-") as td:
            return invoke_cli(
                cmd=cmd, cwd=cwd, timeout_s=timeout_s,
                binary="opencode",
                auth_markers=_AUTH_MARKERS,
                auth_error_msg=f"opencode auth failed for model {self.model} - check API key env var",
                parse_result=_parse_opencode_summary,
                cost_parser=_parse_opencode_cost,
                context_extra={"model": self.model},
                tool_error_suffix=f" (model={self.model})",
                env={**os.environ, "TMPDIR": td},
            )


def _parse_opencode_cost(stdout: str) -> float | None:
    """Extract cost from OpenCode's JSON output.

    Tries top-level `cost`, then `usage.total_cost`, then `usage.cost_usd`.
    Handles both JSONL (iterate lines, last non-None wins) and single-JSON
    (pretty-printed multi-line blob).
    """
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    last_cost: float | None = None
    parsed_lines = 0
    for line in lines:
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        parsed_lines += 1
        c = _extract_cost(data)
        if c is not None:
            last_cost = c
    if last_cost is not None:
        return last_cost
    # If some lines parsed but none carried a cost field, don't re-parse the
    # same text as a single document (same bytes -> same result). Only the
    # pretty-printed-JSON case (parsed_lines == 0) benefits from single-doc parse.
    if parsed_lines > 0:
        return None
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    return _extract_cost(data)


def _extract_cost(data: Any) -> float | None:
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("cost"), (int, float)):
        return float(data["cost"])
    usage = data.get("usage") or {}
    if isinstance(usage, dict):
        for key in ("total_cost", "cost_usd", "cost"):
            val = usage.get(key)
            if isinstance(val, (int, float)):
                return float(val)
    return None


def _parse_opencode_summary(stdout: str) -> tuple[str, list[Path], list[str] | None]:
    """Extract (summary, files_changed, questions) from OpenCode output.

    JSONL-tolerant like CodexAgent's parser. Fields checked in priority order:
    `summary`, `response`, `text`, `content`, `message`.
    """
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    texts: list[str] = []
    files: list[Path] = []
    questions: list[str] | None = None
    parsed_any = 0
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        parsed_any += 1
        if not isinstance(event, dict):
            continue
        for key in ("summary", "response", "text", "content", "message"):
            val = event.get(key)
            if isinstance(val, str):
                texts.append(val)
                break
        item = event.get("item")
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            texts.append(item["text"])
        for key in ("files_changed", "files"):
            fc = event.get(key)
            if isinstance(fc, list):
                files.extend(Path(p) for p in fc if isinstance(p, str))
        qs = event.get("questions")
        if isinstance(qs, list):
            questions = [q for q in qs if isinstance(q, str)] or None
    if parsed_any:
        return (texts[-1] if texts else stdout[:200]), files, questions
    # No per-line parse succeeded — try single-JSON (pretty-printed blob).
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return stdout[:200], [], None
    if not isinstance(data, dict):
        return stdout[:200], [], None
    files_out = [Path(p) for p in data.get("files_changed", []) if isinstance(p, str)]
    qs_raw = data.get("questions")
    if isinstance(qs_raw, list):
        qs_out = [q for q in qs_raw if isinstance(q, str)] or None
    else:
        qs_out = None
    for key in ("summary", "response", "text", "content", "message"):
        val = data.get(key)
        if isinstance(val, str):
            return val, files_out, qs_out
    return stdout[:200], files_out, qs_out
