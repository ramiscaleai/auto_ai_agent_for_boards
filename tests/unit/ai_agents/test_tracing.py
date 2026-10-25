"""Unit tests for ai_agents/tracing.py — Langfuse wiring with no-op fallback."""
from ai_agents.tracing import NoOpTracer, make_tracer


def test_noop_tracer_span_is_a_context_manager():
    tracer = NoOpTracer()
    # Must be enterable + exitable; NoOp yields None by design.
    with tracer.span("agent.run", {"agent": "codex"}) as span:
        assert span is None


def test_make_tracer_returns_noop_when_key_absent():
    tracer = make_tracer(env={})
    assert isinstance(tracer, NoOpTracer)


def test_make_tracer_returns_noop_when_key_empty():
    tracer = make_tracer(env={"LANGFUSE_PUBLIC_KEY": ""})
    assert isinstance(tracer, NoOpTracer)


def test_make_tracer_returns_langfuse_when_creds_present(monkeypatch):
    # We can't actually hit Langfuse in unit tests; just confirm the factory
    # picks the non-NoOp branch when a stubbed _LangfuseTracer class is plugged in.
    import ai_agents.tracing as mod
    from contextlib import nullcontext

    class _StubLangfuseTracer:
        def __init__(self, env):
            self.env = env

        def span(self, name, metadata):
            return nullcontext(None)

    monkeypatch.setattr(mod, "_LangfuseTracer", _StubLangfuseTracer)
    tracer = make_tracer(env={"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"})
    assert not isinstance(tracer, NoOpTracer)


def test_make_tracer_falls_back_to_noop_on_init_failure(monkeypatch, caplog):
    """If Langfuse constructor raises, we log a WARNING and return NoOp — never crash."""
    import ai_agents.tracing as mod

    class _BrokenLangfuseTracer:
        def __init__(self, env):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(mod, "_LangfuseTracer", _BrokenLangfuseTracer)
    with caplog.at_level("WARNING", logger="ai_agents.tracing"):
        tracer = make_tracer(env={"LANGFUSE_PUBLIC_KEY": "pk"})
    assert isinstance(tracer, NoOpTracer)
    assert any("Langfuse init failed" in r.message for r in caplog.records)


def test_langfuse_tracer_flushes_trace_on_exit():
    """_LangfuseTracer.span yields the trace object and flushes on exit."""
    from ai_agents.tracing import _LangfuseTracer

    calls = []

    class _StubClient:
        def trace(self, **kw):
            calls.append(("trace", kw))
            return "TRACE_OBJ"

        def flush(self):
            calls.append(("flush",))

    t = _LangfuseTracer.__new__(_LangfuseTracer)
    t._client = _StubClient()
    with t.span("n", {"k": "v"}) as trace:
        assert trace == "TRACE_OBJ"
    assert calls[0][0] == "trace"
    assert calls[0][1] == {"name": "n", "metadata": {"k": "v"}}
    assert calls[-1] == ("flush",)
