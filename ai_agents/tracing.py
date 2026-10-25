"""Optional Langfuse tracing. No-op when LANGFUSE_PUBLIC_KEY is unset.

See spec section `tracing.py`. A tracer wraps each AIAgent.run() call with a
span carrying {agent, model, task_id, cost_usd, outcome}.

Pinned to langfuse >=2.40,<3 per requirements.txt (v3+ is an OTel-based
rewrite with breaking API changes; this module uses the v2 client API).
"""
from __future__ import annotations

import logging
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Iterator, Mapping, Protocol

_log = logging.getLogger("ai_agents.tracing")


class Tracer(Protocol):
    def span(self, name: str, metadata: dict) -> AbstractContextManager[object]: ...


class NoOpTracer:
    """Used when Langfuse creds are absent. Zero overhead."""

    def span(self, name: str, metadata: dict) -> AbstractContextManager[object]:
        return nullcontext(None)


class _LangfuseTracer:
    """Real Langfuse-backed tracer. Isolated so the import stays optional."""

    def __init__(self, env: Mapping[str, str]) -> None:
        from langfuse import Langfuse  # type: ignore

        self._client = Langfuse(
            public_key=env.get("LANGFUSE_PUBLIC_KEY"),
            secret_key=env.get("LANGFUSE_SECRET_KEY"),
            host=env.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )

    @contextmanager
    def span(self, name: str, metadata: dict) -> Iterator[object]:
        trace = self._client.trace(name=name, metadata=metadata)
        try:
            yield trace
        finally:
            self._client.flush()


def make_tracer(env: Mapping[str, str]) -> Tracer:
    """Return a real tracer if creds are set, else a NoOpTracer."""
    if env.get("LANGFUSE_PUBLIC_KEY"):
        try:
            return _LangfuseTracer(env)
        except Exception as exc:  # noqa: BLE001 — don't take the app down for telemetry
            _log.warning("Langfuse init failed, falling back to NoOpTracer: %s", exc)
    return NoOpTracer()
