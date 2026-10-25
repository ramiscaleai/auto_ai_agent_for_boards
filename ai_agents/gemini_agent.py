"""GeminiAgent — subprocess wrapper around Google's `gemini` CLI.

Personal Google OAuth free tier. Auth via interactive `gemini` first-run login;
credentials at ~/.gemini/oauth_creds.json. See spec section Subclasses.

Target-repo convention: gemini natively reads GEMINI.md in cwd.

Flag notes (observed via `gemini --help` on installed CLI):
- `-p/--prompt <str>` drives non-interactive (headless) mode.
- `-o/--output-format` takes a choice: text | json | stream-json. Values are
  space-separated (e.g. `-o json`), not `=`-joined.
- No `--no-tools` flag; `--approval-mode plan` is the read-only mode
  (choices: default | auto_edit | yolo | plan). We combine it with a prompt
  prefix instructing the model to respond with text only, mirroring CodexAgent.
- `-v/--version` for healthcheck.
- OAuth creds persist at ~/.gemini/oauth_creds.json — probed in healthcheck().
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from ai_agents._subprocess import CHAT_PREFIX, invoke_cli
from ai_agents.base import AIAgent, AgentResult, AgentTask

_log = logging.getLogger("ai_agents.gemini")

# Auth-marker list for use ONLY on non-zero returncode, so a user prompt that
# happens to mention "401" does not raise AgentAuthError on a successful run.
_AUTH_MARKERS = (
    "unauthorized", "401", "403", "not logged in", "login required",
    "expired", "invalid token", "auth method",
)


class GeminiAgent(AIAgent):
    name = "gemini"
    cost_tier = "free"

    def run(self, task: AgentTask) -> AgentResult:
        return self._invoke(self._build_run_cmd(task), task.cwd, task.timeout_s)

    def chat(self, prompt: str, timeout_s: int = 60) -> str:
        cmd = self._build_chat_cmd(prompt)
        with tempfile.TemporaryDirectory() as tmp:
            result = self._invoke(cmd, Path(tmp), timeout_s)
        # Prefer the cleanest parsed text over raw stdout (which includes
        # session metadata and stats). _parse_stdout extracts the response text.
        if result.summary and result.summary != result.output[:200]:
            return result.summary
        return result.output

    def healthcheck(self) -> bool:
        """Installed AND authenticated. `gemini --version` confirms install;
        `~/.gemini/oauth_creds.json` existence is a cheap proxy for 'logged in'.
        A real login-failure still surfaces at run() time via AgentAuthError."""
        try:
            r = subprocess.run(
                ["gemini", "--version"], capture_output=True, timeout=10, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        if r.returncode != 0:
            return False
        return (Path.home() / ".gemini" / "oauth_creds.json").exists()

    # --- helpers ---------------------------------------------------------

    def _build_run_cmd(self, task: AgentTask) -> list[str]:
        # `-p <prompt>` enables non-interactive mode; `-o json` emits a single
        # JSON document with `response` / `error` fields (exit=41 on auth fail).
        # `--approval-mode yolo` auto-approves all tool calls — without it,
        # headless runs block on approval prompts, silently skipping tools like
        # google_web_search (the main reason we prefer gemini for research tasks).
        return ["gemini", "-p", task.prompt, "-o", "json", "--approval-mode", "yolo"]

    def _build_chat_cmd(self, prompt: str) -> list[str]:
        # `--approval-mode plan` is the CLI's read-only mode (no edit/exec tools).
        # Prefix with text-only instruction for defense-in-depth, mirroring Codex.
        return [
            "gemini",
            "--approval-mode", "plan",
            "-o", "json",
            "-p", f"{CHAT_PREFIX}{prompt}",
        ]

    def _invoke(self, cmd: list[str], cwd: Path, timeout_s: int) -> AgentResult:
        return invoke_cli(
            cmd=cmd, cwd=cwd, timeout_s=timeout_s,
            binary="gemini",
            auth_markers=_AUTH_MARKERS,
            auth_error_msg="gemini auth failed — run `gemini` and complete the OAuth flow",
            parse_result=GeminiAgent._parse_stdout,
        )

    @staticmethod
    def _parse_stdout(stdout: str) -> tuple[str, list[Path], list[str] | None]:
        """Return (summary, files_changed, questions) from gemini stdout.

        Shape precedence (same pattern as CodexAgent):
        1. JSONL — iterate lines, accumulate response-like text fields.
        2. Single JSON document — read `response` / `summary` / known keys.
        3. Plain text — first 200 chars.

        Observed single-JSON on `gemini -p ... -o json`:
          {"session_id": "...", "response": "<text>", "stats": {...}}
        And on auth failure (exit=41):
          {"session_id": "...", "error": {"type": "Error", "message": "...", "code": 41}}
        """
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        # Try JSONL first (each line a discrete event).
        summary, files_changed, questions = GeminiAgent._parse_jsonl(lines)
        if summary is not None:
            return summary, files_changed, questions
        # Try single JSON document next.
        single = GeminiAgent._parse_single_json(stdout)
        if single is not None:
            return single
        # Plain text fallback.
        return stdout[:200], [], None

    @staticmethod
    def _parse_jsonl(
        lines: list[str],
    ) -> tuple[str | None, list[Path], list[str] | None]:
        """Parse as JSONL. Return (None, [], None) if fewer than 2 lines parse
        (since a single-JSON document typically pretty-prints across many lines
        but only one `json.loads` succeeds on the full blob, not per-line)."""
        texts: list[str] = []
        files: list[Path] = []
        questions: list[str] | None = None
        parsed = 0
        for line in lines:
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            parsed += 1
            if not isinstance(event, dict):
                continue
            for key in ("text", "content", "response", "message"):
                val = event.get(key)
                if isinstance(val, str):
                    texts.append(val)
                    break
            s = event.get("summary")
            if isinstance(s, str):
                texts.append(s)
            for key in ("files_changed", "files"):
                fc = event.get(key)
                if isinstance(fc, list):
                    files.extend(Path(p) for p in fc if isinstance(p, str))
            qs = event.get("questions")
            if isinstance(qs, list):
                questions = [q for q in qs if isinstance(q, str)] or None
        if parsed >= 2:
            return (texts[-1] if texts else " ".join(lines)[:200]), files, questions
        return None, [], None

    @staticmethod
    def _parse_single_json(
        stdout: str,
    ) -> tuple[str, list[Path], list[str] | None] | None:
        """Parse the full stdout as one JSON document. Return None on failure."""
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        summary = ""
        for key in ("response", "summary", "text", "content", "message"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                summary = val
                break
        if not summary:
            summary = stdout[:200]
        files: list[Path] = []
        for key in ("files_changed", "files"):
            fc = data.get(key)
            if isinstance(fc, list):
                files.extend(Path(p) for p in fc if isinstance(p, str))
        qs = data.get("questions")
        if isinstance(qs, list):
            questions = [q for q in qs if isinstance(q, str)] or None
        else:
            questions = None
        return summary, files, questions
