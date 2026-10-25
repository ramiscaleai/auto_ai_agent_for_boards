"""Shared subprocess plumbing for CLI-backed AIAgent implementations.

CodexAgent, GeminiAgent, and OpenCodeAgent all need to (a) run a subprocess
under a timeout, (b) map common failures to AIAgentErrors, (c) check
auth-marker strings ONLY on non-zero exit, (d) build an AgentResult on
success. This module centralizes that plumbing so each agent file focuses on
what actually differs between them: command construction, auth-marker strings,
output parsing, and (optionally) cost extraction.
"""
from __future__ import annotations

import logging
import select
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from ai_agents.base import AgentResult
from ai_agents.errors import (
    AgentAuthError,
    AgentNotInstalledError,
    AgentTimeoutError,
    AgentToolError,
)

_log = logging.getLogger("ai_agents._subprocess")

CHAT_PREFIX = (
    "You must not call any tools or edit any files. "
    "Respond with text only.\n\n"
)

ParseResult = Callable[[str], tuple[str, list[Path], list[str] | None]]
CostParser = Callable[[str], float | None]


def invoke_cli(
    *,
    cmd: list[str],
    cwd: Path,
    timeout_s: int,
    binary: str,
    auth_markers: tuple[str, ...],
    auth_error_msg: str,
    parse_result: ParseResult,
    cost_parser: CostParser | None = None,
    context_extra: dict[str, Any] | None = None,
    tool_error_suffix: str = "",
    env: dict[str, str] | None = None,
) -> AgentResult:
    """Run `cmd` in `cwd`, map failures to AIAgent exceptions, parse success output.

    - `binary` names the CLI (e.g. "codex") for error messages and log lines.
    - `auth_markers` are lowercase substrings; presence on non-zero exit raises
      AgentAuthError(auth_error_msg). Otherwise raises AgentToolError.
    - `parse_result(stdout)` returns (summary, files_changed, questions).
    - `cost_parser(stdout)` is optional (Codex/Gemini pass None; OpenCode extracts $).
    - `context_extra` is merged into every exception context (e.g. {"model": ...}).
      invoke_cli's own observation keys (cmd / stdout_tail / stderr_tail) always
      win over colliding keys in context_extra, so debuggers see ground truth.
    - `tool_error_suffix` appends to the AgentToolError message (e.g. " (model=X)").
    - `env` (optional) replaces the child's environment. Pass
      ``{**os.environ, "TMPDIR": <throwaway>}`` to sandbox a binary that dumps
      scratch into $TMPDIR (opencode, a Bun standalone, extracts its embedded
      libs there). None = inherit the parent env (Codex/Gemini are untouched).
    """
    extra = dict(context_extra or {})
    t0 = time.monotonic()
    proc = _run_or_raise(cmd, cwd, timeout_s, binary, extra, env)
    duration = time.monotonic() - t0
    if proc.returncode != 0:
        _raise_on_failure(
            proc, binary, auth_markers, auth_error_msg, tool_error_suffix, extra,
        )
    summary, files_changed, questions = parse_result(proc.stdout)
    cost = cost_parser(proc.stdout) if cost_parser else None
    return AgentResult(
        success=True,
        summary=summary,
        files_changed=files_changed,
        output=proc.stdout,
        cost_usd=cost,
        duration_s=duration,
        questions=questions,
    )


def _run_or_raise(
    cmd: list[str], cwd: Path, timeout_s: int, binary: str, extra: dict[str, Any],
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Stream subprocess stdout/stderr line-by-line; kill on idle (no output) timeout.

    ``env=None`` inherits the parent environment (default). A non-None ``env`` is
    the FULL child environment (caller merges os.environ itself)."""
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
    except FileNotFoundError as exc:
        _log.warning("%s: binary not found on PATH (cmd=%s)", binary, cmd[0])
        raise AgentNotInstalledError(
            f"{binary} binary not found on PATH",
            context={**extra, "cmd": cmd[0]},
        ) from exc

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    last_activity = time.monotonic()
    stdout_eof = stderr_eof = False

    while not (stdout_eof and stderr_eof):
        idle_s = time.monotonic() - last_activity
        remaining = timeout_s - idle_s
        if remaining <= 0:
            proc.kill()
            proc.wait()
            _log.warning("%s: idle timeout — no output for %ds", binary, timeout_s)
            raise AgentTimeoutError(
                f"{binary} produced no output for {timeout_s}s",
                context={**extra, "cmd": cmd[:2]},
            )
        fds = ([proc.stdout] if not stdout_eof else []) + ([proc.stderr] if not stderr_eof else [])
        readable, _, _ = select.select(fds, [], [], min(remaining, 5.0))
        if not readable:
            if proc.poll() is not None:
                break
            continue
        for fd in readable:
            line = fd.readline()
            if not line:
                if fd is proc.stdout:
                    stdout_eof = True
                else:
                    stderr_eof = True
                continue
            last_activity = time.monotonic()
            if fd is proc.stdout:
                stdout_parts.append(line)
                _log.debug("%s: %s", binary, line.rstrip())
            else:
                stderr_parts.append(line)
                _log.debug("%s stderr: %s", binary, line.rstrip())

    for line in proc.stdout:
        stdout_parts.append(line)
    for line in proc.stderr:
        stderr_parts.append(line)
    proc.wait()
    return subprocess.CompletedProcess(cmd, proc.returncode, "".join(stdout_parts), "".join(stderr_parts))


def _raise_on_failure(
    proc: subprocess.CompletedProcess,
    binary: str,
    auth_markers: tuple[str, ...],
    auth_error_msg: str,
    tool_error_suffix: str,
    extra: dict[str, Any],
) -> None:
    """On non-zero exit, log-warn and raise AgentAuthError (if auth marker matched)
    or AgentToolError. invoke_cli's own keys win over any context_extra collisions."""
    combined = (proc.stdout + proc.stderr).lower()
    stderr_tail = proc.stderr[-500:]
    if any(marker in combined for marker in auth_markers):
        _log.warning("%s: auth failure (rc=%d): %s", binary, proc.returncode, stderr_tail[-200:])
        raise AgentAuthError(
            auth_error_msg,
            context={**extra, "stderr_tail": stderr_tail},
        )
    _log.warning("%s: exit %d: %s", binary, proc.returncode, stderr_tail[-200:])
    raise AgentToolError(
        f"{binary} exit {proc.returncode}{tool_error_suffix}",
        context={**extra, "stdout_tail": proc.stdout[-500:], "stderr_tail": stderr_tail},
    )
