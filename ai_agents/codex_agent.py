"""CodexAgent — subprocess wrapper around the OpenAI `codex` CLI.

Codex uses subscription auth (ChatGPT Plus/Pro) via `codex login`; auth lives
in ~/.codex/auth.json. See spec section Subclasses.

Target-repo convention: codex natively reads AGENTS.md in cwd. We do not inject.

Flag notes (observed on codex-cli 0.118.0 via `codex exec --help`):
- `--json` exists as documented — used for run() structured output.
- `--sandbox <MODE>` takes a positional value (read-only|workspace-write|
  danger-full-access). The spec assumed `--sandbox-read-only` (single flag);
  actual is `--sandbox read-only` (two tokens). Substituted.
- No `--no-tools` flag exists on `codex exec`. For chat() text-only mode we
  combine `--sandbox read-only` (blocks file writes) with a prompt prefix
  instructing the model to respond with text only. `--ephemeral` avoids
  persisting session files for the throwaway chat call.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, cast

from ai_agents._subprocess import CHAT_PREFIX, invoke_cli
from ai_agents.base import AIAgent, AgentResult, AgentTask

_log = logging.getLogger("ai_agents.codex")

_AUTH_MARKERS = ("unauthorized", "401", "403", "not logged in", "expired")
DEFAULT_CODEX_MODEL = "gpt-5.5"
DEFAULT_CODEX_REASONING_EFFORT = "xhigh"
ReasoningEffort = Literal["low", "medium", "high", "xhigh"]
_REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}


class CodexAgent(AIAgent):
    name = "codex"
    cost_tier = "free"

    def __init__(
        self,
        *,
        model: str = DEFAULT_CODEX_MODEL,
        reasoning_effort: str = DEFAULT_CODEX_REASONING_EFFORT,
    ) -> None:
        model = model.strip()
        reasoning_effort = reasoning_effort.strip()
        if not model:
            raise ValueError("codex model must be non-empty")
        if reasoning_effort not in _REASONING_EFFORTS:
            raise ValueError(
                "codex reasoning_effort must be one of "
                f"{sorted(_REASONING_EFFORTS)}"
            )
        self.model = model
        self.reasoning_effort = cast(ReasoningEffort, reasoning_effort)

    def run(self, task: AgentTask) -> AgentResult:
        return self._invoke(self._build_run_cmd(task), task.cwd, task.timeout_s)

    def chat(self, prompt: str, timeout_s: int = 60) -> str:
        cmd = self._build_chat_cmd(prompt)
        with tempfile.TemporaryDirectory() as tmp:
            result = self._invoke(cmd, Path(tmp), timeout_s)
        # _parse_stdout extracts the last agent_message; prefer that over raw
        # stdout (which includes banner, echoed prompt, and "tokens used" footer).
        if result.summary and result.summary != result.output[:200]:
            return result.summary
        return result.output

    def healthcheck(self) -> bool:
        """Installed AND authenticated. `codex --version` confirms install;
        `~/.codex/auth.json` existence is a cheap proxy for 'logged in'.
        A real login-failure still surfaces at run() time via AgentAuthError."""
        try:
            r = subprocess.run(
                ["codex", "--version"], capture_output=True, timeout=10, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        if r.returncode != 0:
            return False
        return (Path.home() / ".codex" / "auth.json").exists()

    # --- helpers ---------------------------------------------------------

    def _build_run_cmd(self, task: AgentTask) -> list[str]:
        # `--sandbox danger-full-access` bypasses bwrap (needed in containerised envs
        # where bwrap loopback namespacing fails with EPERM). Security is handled
        # at the VM/container boundary rather than the bwrap sandbox.
        # `--json` emits JSONL events; `--skip-git-repo-check` lets us operate
        # in arbitrary cwds. `exec` is non-interactive.
        return [
            "codex", "exec",
            "--model", self.model,
            "-c", f'model_reasoning_effort="{self.reasoning_effort}"',
            "--sandbox", "danger-full-access",
            "--json",
            "--skip-git-repo-check",
            task.prompt,
        ]

    def _build_chat_cmd(self, prompt: str) -> list[str]:
        # No CLI flag fully suppresses tool use on codex exec; we combine
        # `--sandbox read-only` (blocks writes) with a prompt prefix, and use
        # `--ephemeral` so the throwaway chat call leaves no session on disk.
        return [
            "codex", "exec",
            "--model", self.model,
            "-c", f'model_reasoning_effort="{self.reasoning_effort}"',
            "--sandbox", "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            f"{CHAT_PREFIX}{prompt}",
        ]

    def _invoke(self, cmd: list[str], cwd: Path, timeout_s: int) -> AgentResult:
        return invoke_cli(
            cmd=cmd, cwd=cwd, timeout_s=timeout_s,
            binary="codex",
            auth_markers=_AUTH_MARKERS,
            auth_error_msg="codex auth failed — run `codex login`",
            parse_result=CodexAgent._parse_stdout,
            context_extra={
                "model": self.model,
                "reasoning_effort": self.reasoning_effort,
            },
            tool_error_suffix=(
                f" (model={self.model}, reasoning_effort={self.reasoning_effort})"
            ),
        )

    @staticmethod
    def _parse_stdout(stdout: str) -> tuple[str, list[Path], list[str] | None]:
        """Return (summary, files_changed, questions) from codex stdout.

        Handles three shapes in order of preference:
        1. JSONL — iterate lines, pick the most recent 'agent_message' item text as summary.
           (codex exec --json actually emits JSONL in codex-cli >=0.118; single-blob
           parsing would silently return empty results.)
        2. Single JSON document with `summary` / `files_changed` / `questions` keys.
        3. Plain text — first 200 chars.

        Note: files_changed is typically empty for real codex output (the CLI does
        not emit that field); runner.py is responsible for computing it via `git
        diff` post-run.
        """
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        agent_messages: list[str] = []
        files_changed: list[Path] = []
        questions: list[str] | None = None
        parsed_any = False
        for line in lines:
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            parsed_any = True
            if not isinstance(event, dict):
                continue
            item = event.get("item") or {}
            if isinstance(item, dict):
                if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    agent_messages.append(item["text"])
                text = item.get("text")
                if isinstance(text, str) and not agent_messages:
                    agent_messages.append(text)
            if "summary" in event and isinstance(event["summary"], str):
                agent_messages.append(event["summary"])
            if "files_changed" in event:
                files_changed.extend(
                    Path(p) for p in event["files_changed"] if isinstance(p, str)
                )
            if "questions" in event and isinstance(event["questions"], list):
                questions = [q for q in event["questions"] if isinstance(q, str)] or None
        if parsed_any:
            summary = agent_messages[-1] if agent_messages else stdout[:200]
            return summary, files_changed, questions
        # Fallback: single-JSON (legacy) or plain text.
        try:
            data = json.loads(stdout)
            summary = str(data.get("summary", "")).strip() or stdout[:200]
            files = [Path(p) for p in data.get("files_changed", []) if isinstance(p, str)]
            qs = data.get("questions") or None
            return summary, files, qs
        except (json.JSONDecodeError, ValueError):
            return stdout[:200], [], None
