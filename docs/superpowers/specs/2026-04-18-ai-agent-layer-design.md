# AI Agent Layer — Design

**Date:** 2026-04-18
**Status:** Approved (pre-implementation)
**Sub-project:** B — AI Agent layer (one of six from README decomposition)

## Goal

Build a reusable Python layer that turns a free-form task description into file edits inside a given repo directory, delegating to one of several AI coding tools. The layer must:

1. Support **four backends** — `codex` (subscription), `gemini` (subscription), `opencode --model openrouter/...` (API), `opencode --model anthropic/...` (API).
2. Cascade through a **config-declared priority chain** on failure. Default chain puts free-tier agents before paid.
3. Be **extensible** — adding a new LLM = new YAML entry, no Python changes (unless the vendor needs custom behavior).
4. Expose the same abstraction for **structured non-code LLM calls** (classification, "am-I-stuck?", comment drafting), preferring subscription-backed agents so those calls cost nothing.
5. Enforce a **per-task and daily spend ceiling** so a runaway loop on a paid fallback can't burn the Anthropic/OpenRouter key.

## Non-goals (YAGNI)

- Parallel execution of multiple agents on one task (README is explicit: one task at a time).
- Git workflow (branch-per-task, merge-back) — that's sub-project D.
- Board polling, task-to-prompt translation, repo identification from `repos.md` — sub-projects C, E.
- MCP tool-bus wiring — defer until the main loop needs it.
- Streaming agent output back to the caller — log files serve as the progress channel.
- Agent-specific prompt scaffolding — each CLI handles its own system prompt; we pass the user prompt as-is.
- Any attempt to reuse Claude Pro/Max OAuth — **forbidden by Anthropic ToS since Feb 2026**. `ClaudeAgent` is `OpenCodeAgent` configured with an `anthropic/...` model and an API key.

## Architecture

```
ai_agents/                              # new Python package — provider-agnostic library
├── __init__.py
├── base.py                             # AIAgent ABC + AgentTask + AgentResult
├── codex_agent.py                      # CodexAgent — subprocess codex CLI
├── gemini_agent.py                     # GeminiAgent — subprocess gemini CLI
├── opencode_agent.py                   # OpenCodeAgent(model=...) — subprocess opencode CLI
├── registry.py                         # AgentRegistry — loads agents.yml + .env
├── runner.py                           # AgentRunner — coding fallback chain
├── cost_guard.py                       # CostGuard — per-task + daily spend caps
├── structured_llm.py                   # StructuredLLM ABC + 3 impls + vanilla JSON prompt
├── tracing.py                          # Langfuse wiring (no-op if creds absent)
└── errors.py                           # typed exceptions

config/
└── agents.yml                          # registry + coding chain + structured chain (committed)

scripts/ai_agents/
├── requirements.txt                    # new deps pinned
├── install_cli_tools.sh                # npm installs + auth-step print
├── setup_venv.sh                       # extends existing .venv
└── smoke_test.sh                       # wraps pytest + CLI healthchecks

tests/unit/ai_agents/                   # fast, no network (7 files)
tests/e2e/ai_agents/                    # gated by E2E=1 (6 files)
```

### Boundaries

- `ai_agents/` knows nothing about Trello, `repos.md`, or git workflow.
- `config/agents.yml` is the declarative registry — adding DeepSeek, Grok, or a local Ollama model is a YAML edit.
- `scripts/ai_agents/` is operator-facing (setup, smoke tests).

### Dependency tree

```
runner ─▶ registry ─▶ {codex, gemini, opencode}_agent ─▶ base
runner ─▶ cost_guard      (wraps paid calls)
runner ─▶ tracing         (wraps all calls)
structured_llm            (standalone; used by future sub-projects)
```

## Components

### `base.py` — ABC + dataclasses

```python
@dataclass(frozen=True)
class AgentTask:
    prompt: str
    cwd: Path
    allowed_tools: frozenset[str] = frozenset({"read", "write", "bash"})
    timeout_s: int = 1800

@dataclass(frozen=True)
class AgentResult:
    success: bool
    summary: str
    files_changed: list[Path]
    output: str                              # full tool stdout (also written to log file)
    cost_usd: float | None                   # None for subscription tiers
    duration_s: float
    error: str | None = None
    questions: list[str] | None = None

class AIAgent(ABC):
    name: str
    cost_tier: Literal["free", "low", "medium", "high"]

    @abstractmethod
    def run(self, task: AgentTask) -> AgentResult: ...

    @abstractmethod
    def chat(self, prompt: str, timeout_s: int = 60) -> str:
        """Text-only — no tool use, no file edits. Used by AgentStructuredLLM."""

    @abstractmethod
    def healthcheck(self) -> bool:
        """Verify CLI installed + authenticated. Called once per registry load."""
```

`files_changed` is derived from `git diff` after the run — we don't trust the agent to report accurately.

### Subclasses

Each is a thin adapter built on `subprocess.run([binary, ...args], cwd=task.cwd, timeout=task.timeout_s, capture_output=True)`. **Never `shell=True`**; arg list only. Output is tee'd to `logs/ai_agents/<agent>-<task_id>-<ts>.log` as it runs.

| Subclass | `run()` command | `chat()` command | `cost_usd` |
|---|---|---|---|
| `CodexAgent` | `codex exec --output-schema <path> "${prompt}"` | `codex exec --sandbox-read-only --no-tools "${prompt}"` | `None` |
| `GeminiAgent` | `gemini -p "${prompt}" --output-format json` | `gemini -p "${prompt}" --approval-mode=never` | `None` |
| `OpenCodeAgent(model=...)` | `opencode run --model <model> --format json "${prompt}"` | `opencode run --model <model> --no-tools "${prompt}"` | parsed from JSON |

**CLI-flag verification at implementation time:** The exact chat-mode flags above (`--no-tools`, `--sandbox-read-only`, `--approval-mode=never`) are the intended behavior but must be **verified against each CLI's `--help` output when the subclass is coded**. If a flag doesn't exist or has renamed, the implementer picks the closest equivalent and falls back to a strong system prompt forbidding tool use (e.g. `"You must not call any tools or edit any files. Respond with text only."`) prepended to the user prompt.

Two `OpenCodeAgent` instances sit in the registry: `openrouter` (model `openrouter/anthropic/claude-sonnet-4.5`, `cost_tier: medium`) and `claude` (model `anthropic/claude-opus-4-7`, `cost_tier: high`).

### Target-repo convention files (native, not managed by this library)

`run()` operates with `cwd=task.cwd` (the target repo). Each CLI auto-ingests the target repo's convention file natively as its per-repo system prompt:

- Codex → `AGENTS.md`
- Gemini → `GEMINI.md`
- OpenCode → `AGENTS.md` (verify at implementation; may also read `opencode.json`)

This library does **not** author, inject, substitute, or fallback between convention files. If the running agent's convention file is missing from the target repo, the CLI proceeds with its default context; the runner logs an INFO line (`no <filename> in target repo; agent running with default CLI context`). Sub-project E (main loop) may choose to pre-validate convention-file presence before dispatching a task — that's an E concern, not B's.

Per-repo convention is the target repo owner's responsibility. Typical patterns (mentioned for reference only; not enforced here):
- A single `AGENTS.md` with symlinks for `GEMINI.md` / `CLAUDE.md` — one source of truth across all tools.
- One file per tool, each with tool-specific phrasing.
- No convention file — agents run with defaults (quality may drop but the call still works).

### `chat()` isolation

`chat()` runs in an **ephemeral empty tempdir** (`tempfile.TemporaryDirectory()`). Because the tempdir has no convention files, no auto-loading happens — non-code structured calls are not polluted by any target repo's coding conventions. The only priming is the hardcoded Python JSON wrapper in `_build_json_prompt` (defined in `structured_llm.py`).

### `registry.py`

```python
class AgentRegistry:
    @classmethod
    def load(cls, yaml_path: Path, env: Mapping[str, str]) -> "AgentRegistry": ...
    def coding_chain(self) -> list[AIAgent]: ...            # from coding.priority
    def structured_chain(self) -> list[StructuredLLM]: ...  # from structured_llm.priority
    def get(self, name: str) -> AIAgent: ...
    def build_structured_llm(self) -> StructuredLLM: ...    # returns ChainedStructuredLLM
    def default_structured_agent(self) -> AIAgent: ...      # first free agent in coding chain
```

On load: instantiates every agent in `agents:`, runs `healthcheck()` on each, logs which are up, builds both chains. Parses `structured_llm.priority` entries — bare names resolve to `AgentStructuredLLM(registry.get(name))`; entries prefixed `litellm:` resolve to `LiteLLMStructuredLLM(model=...)`.

Fail-fast at load:
- `coding.priority` missing → `ConfigError` exit 2.
- Any priority-chain name not defined in `agents:` → `ConfigError`.
- None of the coding agents pass healthcheck → `WARNING` (don't crash; structured-only may still work).

### `runner.py`

```python
class AgentRunner:
    def __init__(self, registry: AgentRegistry, cost_guard: CostGuard, tracer: Tracer): ...
    def run(self, task: AgentTask) -> AgentResult: ...
```

Loops `registry.coding_chain()` in config order. On each agent:

1. `cost_guard.precheck(agent)` — raises `BudgetExceededError` if over daily cap (free-tier bypasses).
2. `tracer.span("agent.run", {...})` — no-op if Langfuse disabled.
3. `agent.run(task)` — returns `AgentResult`.
4. `cost_guard.record(result)` always after `run()` returns (no-op when `result.cost_usd is None`). Paid results that breach the per-task cap still persist the spend and raise `BudgetExceededError`.

Failure handling:
- `AgentToolError`, `AgentTimeoutError`, `AgentAuthError` → log WARNING, continue to next agent.
- `BudgetExceededError` → **propagates** (not recoverable by trying a more expensive agent).
- All agents fail → raise `AllAgentsFailedError(attempted=[...], errors=[...])`.

### `cost_guard.py`

```python
class CostGuard:
    def __init__(self, per_task_cap_usd: float, daily_cap_usd: float, state_path: Path): ...
    def precheck(self, agent: AIAgent) -> None: ...     # raises BudgetExceededError
    def record(self, result: AgentResult) -> None: ...  # persists JSON
```

- Per-task cap enforced by comparing `result.cost_usd` at record time; exceeding it still records the spend but raises `BudgetExceededError` so the caller sees the breach.
- Daily cap read from JSON state file (`~/.cache/auto_ai_agent/spend.json`), date-keyed with rollover.
- Free-tier agents (`cost_tier == "free"`) bypass `precheck` entirely. `record()` is a no-op when `result.cost_usd is None` (subscription tier).
- Config via `.env`: `COST_PER_TASK_USD=0.50`, `COST_PER_DAY_USD=5.00`.

### `structured_llm.py`

```python
class StructuredLLM(ABC):
    @abstractmethod
    def ask(self, prompt: str, schema: type[BaseModel], max_retries: int = 2) -> BaseModel: ...

class AgentStructuredLLM(StructuredLLM):
    """Wraps any AIAgent (codex, gemini, or OpenCodeAgent)."""
    def __init__(self, agent: AIAgent): ...
    # Builds vanilla prompt via _build_json_prompt(); calls agent.chat();
    # parses JSON; on ValidationError, retries with a correction prompt.

class LiteLLMStructuredLLM(StructuredLLM):
    """Direct LiteLLM + Instructor call. Paid."""
    def __init__(self, model: str, cost_guard: CostGuard | None = None): ...

class ChainedStructuredLLM(StructuredLLM):
    """Composite — tries each provider in priority order."""
    def __init__(self, providers: list[StructuredLLM]): ...
```

Vanilla JSON prompt (private helper):

```python
def _build_json_prompt(question: str, schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    return (
        f"Respond with ONLY valid JSON matching this schema:\n\n{schema_json}\n\n"
        f"No prose, no code fences, no markdown — only the raw JSON object.\n\n"
        f"Task: {question}"
    )
```

Correction prompt on `ValidationError`:

```
Your previous response failed validation: <error>.
Respond again with ONLY valid JSON matching the schema.
```

### `tracing.py`

```python
@contextmanager
def span(name: str, metadata: dict) -> Iterator[Span]: ...
```

No-op if `LANGFUSE_PUBLIC_KEY` unset. Otherwise emits Langfuse trace with token counts, cost, agent name, outcome.

### `errors.py`

```python
class AIAgentError(RuntimeError):
    def __init__(self, msg: str, *, context: dict | None = None): ...

class ConfigError(AIAgentError): ...
class AgentNotInstalledError(AIAgentError): ...
class AgentAuthError(AIAgentError): ...
class AgentToolError(AIAgentError): ...
class AgentTimeoutError(AIAgentError): ...
class BudgetExceededError(AIAgentError): ...
class StructuredLLMParseError(AIAgentError): ...
class AllAgentsFailedError(AIAgentError): ...
```

Every raise site populates `context` with `task_id`, `agent_name`, redacted `cmd`, last 500 chars of `stdout_tail`.

## Configuration

### `config/agents.yml` (committed)

```yaml
# 1. Registry — what agents exist.
agents:
  codex:      { class: CodexAgent,    cost_tier: free }
  gemini:     { class: GeminiAgent,   cost_tier: free }
  openrouter: { class: OpenCodeAgent, model: openrouter/anthropic/claude-sonnet-4.5, cost_tier: medium }
  claude:     { class: OpenCodeAgent, model: anthropic/claude-opus-4-7,              cost_tier: high }

# 2. Coding agent — for AIAgent.run() (file-editing work).
coding:
  priority: [codex, gemini, openrouter, claude]

# 3. Structured LLM — for AgentStructuredLLM (non-code JSON-schema calls).
structured_llm:
  priority:
    - codex                                  # free
    - gemini                                 # free
    - openrouter                             # paid — OpenCodeAgent in chat mode
    - claude                                 # paid — OpenCodeAgent in chat mode
    - litellm:openai/gpt-4o-mini             # paid — LiteLLM + Instructor fallback
```

### `.env` overrides (not committed)

```bash
# Auth (required per agent you intend to use):
ANTHROPIC_API_KEY=...               # OpenCodeAgent with anthropic/... model
OPENROUTER_API_KEY=...              # OpenCodeAgent with openrouter/... model
# codex & gemini auth live in ~/.codex/auth.json and ~/.gemini/ (via their CLI login)

# Budget (optional — defaults shown):
COST_PER_TASK_USD=0.50
COST_PER_DAY_USD=5.00

# Overrides for priority chains (optional):
AI_CODING_PRIORITY=gemini,codex,openrouter,claude
AI_STRUCTURED_PRIORITY=codex,gemini,litellm:openai/gpt-4o-mini

# Observability (optional — tracing disabled if absent):
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=https://cloud.langfuse.com
```

### Config precedence (highest wins)

| Source | Example | Loaded |
|---|---|---|
| `.env` `AI_*` / `COST_*` | `AI_CODING_PRIORITY=...` | at startup |
| `config/agents.yml` | `coding.priority: [...]` | at startup |
| Hard-coded defaults | `cost_tier="free"` for Codex/Gemini | dataclass defaults |

### Cost-awareness

At load, if a priority chain places a paid entry before a free one, the registry logs:

```
WARNING: coding.priority places paid 'claude' above free 'codex' — intentional?
```

Doesn't block; just flags.

## Data flow

### Startup

```
1. load_dotenv(".env")
2. yaml.safe_load("config/agents.yml")
3. apply_env_overrides(yaml, os.environ)
4. registry = AgentRegistry.load(yaml)
     → instantiate each agent → healthcheck() each → log which are up
     → parse coding.priority → coding_chain
     → parse structured_llm.priority → structured_providers
5. cost_guard = CostGuard(per_task_cap_usd, daily_cap_usd, state_path)
6. tracer = Langfuse(...) if LANGFUSE_PUBLIC_KEY else NoOpTracer()
7. runner = AgentRunner(registry, cost_guard, tracer)
8. structured = registry.build_structured_llm()   # ChainedStructuredLLM
```

### `AgentRunner.run(task)` — coding

```
for agent in registry.coding_chain():
    with tracer.span("agent.run", {"agent": agent.name, "task_id": task_id}):
        try:
            cost_guard.precheck(agent)
            result = agent.run(task)
            cost_guard.record(result)
            if result.success: return result
        except (AgentAuthError, AgentToolError, AgentTimeoutError):
            continue  # try next agent
        except BudgetExceededError:
            raise     # short-circuit — don't try a more expensive agent
raise AllAgentsFailedError(attempted=[...], errors=[...])
```

### `ChainedStructuredLLM.ask(prompt, schema)` — structured

```
for provider in self._providers:
    try: return provider.ask(prompt, schema, max_retries=2)
    except AIAgentError: continue                    # covers StructuredLLMParseError subclass
raise AllAgentsFailedError
```

Per-provider retry inside `AgentStructuredLLM.ask`:

```
for attempt in range(max_retries + 1):
    text = agent.chat(current_prompt)
    try: return schema.model_validate_json(text.strip())
    except ValidationError as e:
        current_prompt = _correction_prompt(e, original_prompt)
raise StructuredLLMParseError
```

### Example chain behaviors

Using default priority `[codex, gemini, openrouter, claude]`:

- **Happy path:** codex succeeds → done. No other agents touched.
- **Codex rate-limited:** codex `AgentToolError` → gemini succeeds → done. No paid calls.
- **Both free down:** codex + gemini fail → `cost_guard.precheck(openrouter)` OK → openrouter succeeds with cost recorded.
- **Budget exhausted:** free agents fail → `cost_guard.precheck(openrouter)` raises `BudgetExceededError` → runner propagates; caller sees failed task without claude ever attempted.
- **User reorders `[claude, codex, ...]`:** claude tried first, paid cost incurred. Startup logs `WARNING` about paid-before-free.

## Error handling

| Layer | Raises | Caught by |
|---|---|---|
| Subclass | `AgentNotInstalledError`, `AgentAuthError`, `AgentToolError`, `AgentTimeoutError` | `AgentRunner` → next agent |
| `CostGuard` | `BudgetExceededError` | `AgentRunner` → propagates |
| `StructuredLLM` provider | `StructuredLLMParseError` (post-retry), `AIAgentError` | `ChainedStructuredLLM` → next provider |
| `AgentRunner` / `ChainedStructuredLLM` | `AllAgentsFailedError` with full attempt list | caller |
| Registry load | `ConfigError` | `main` → exit 2 |

Every exception carries a `context` dict: `task_id`, `agent_name`, redacted `cmd`, `stdout_tail` (last 500 chars). One grep, one post-mortem.

### Logging

Structured JSON lines, every line includes `task_id`:

| Event | Level | Fields |
|---|---|---|
| Agent invoked | INFO | agent, model, task_id, prompt_len |
| Subprocess stdout line | DEBUG | agent, task_id, line |
| Agent succeeded | INFO | agent, task_id, duration_s, cost_usd, files_changed_count |
| Agent failed (will retry next) | WARNING | agent, task_id, error_class, will_retry_with_next |
| Chain exhausted | ERROR | task_id, attempted_agents, errors |
| Budget check failed | ERROR | task_id, daily_spend, cap |
| Structured validate failed | WARNING | task_id, attempt, validation_error |

`redact_secrets()` is applied to every log line — env var names matching `*_API_KEY|*_TOKEN|*_SECRET` have their values replaced with `***` in any string that reaches a handler.

## Security (CLAUDE.md rules 6, 8)

- **Secrets:** `.env` only. Never logged, never in error messages, never passed as CLI args. `.gitignore` already covers `.env`.
- **Subprocess:** always `subprocess.run([binary, ...args], shell=False)`. Arg list, no f-string interpolation into a shell string — the user prompt cannot break out.
- **Prompt delivery:** via arg list or stdin (`input=prompt.encode()`), never concatenated into a shell command.
- **File-system scope:** subprocess runs with `cwd=task.cwd`. No `--allow=/...` patterns wider than the repo. All four CLIs honor `cwd` as their sandbox root.
- **`allowed_tools` honored:** if `task.allowed_tools` is a subset of `{read, write, bash}`, translate to the CLI's flags (e.g., OpenCode `--no-bash`, Gemini `--approval-mode=never`). Caller can force read-only.
- **Log redaction:** `redact_secrets()` applied universally.
- **Cost ceiling:** `CostGuard` is the last line of defense — an LLM loop on a paid model can't exceed the per-task cap.

## Testing (CLAUDE.md BDD: unit + e2e)

### Unit — `tests/unit/ai_agents/` (7 files, ~400 LOC, no network)

| File | Covers |
|---|---|
| `test_agent_task.py` | `AgentTask` / `AgentResult` invariants |
| `test_registry.py` | YAML → registry, env overrides, unknown-agent `ConfigError`, missing `coding.priority` → error, paid-before-free WARNING |
| `test_runner.py` | Fallback with `FakeAgent` stubs: success on 1st; failure→success; all-fail→`AllAgentsFailedError`; budget-exceeded short-circuit |
| `test_cost_guard.py` | Per-task cap, daily cap, date rollover, free-tier bypass |
| `test_structured_llm.py` | `FakeAgent.chat()` returning good/bad JSON; retry correction prompt; mixed chain fallback incl. `litellm:` entry |
| `test_errors_context.py` | Exception `.context` has required keys; secrets redacted |
| `test_subclass_cmd_build.py` | Each subclass: `_build_run_cmd(task)` and `_build_chat_cmd(prompt)` produce expected arg list (shell=False, no interpolation) |

`FakeAgent(AIAgent)` fixture provides deterministic success/failure/cost without subprocess.

### E2E — `tests/e2e/ai_agents/` (6 files, ~200 LOC, gated by `E2E=1`)

| File | Uses | Proves |
|---|---|---|
| `test_codex_healthcheck.py` | real `codex` CLI | subscription auth works |
| `test_gemini_healthcheck.py` | real `gemini` CLI | same |
| `test_opencode_healthcheck.py` | real `opencode` + `OPENROUTER_API_KEY` (cheapest model, prompt="ping") | JSON parsing, cost extraction; <$0.01 per run |
| `test_end_to_end_hello.py` | first healthy agent in chain | `run(prompt="create hello.py printing 'hi'")` produces file; cost ≤ $0.10 |
| `test_structured_llm_classify.py` | first free agent's `chat()` | `StructuredLLM.ask("classify this task", Schema)` returns valid Pydantic |
| `test_chain_fallback.py` | two live agents | primary forced to fail (bad arg) → second succeeds |

E2E counts against `CostGuard` daily cap. CI uses `COST_PER_DAY_USD=0.50` for the e2e job.

### BDD mapping

| Behavior | Test file |
|---|---|
| Given task, When codex healthy, Then it runs first and returns files_changed | `test_end_to_end_hello.py` |
| Given codex down, When task arrives, Then gemini is tried next | `test_runner.py` |
| Given all free fail, When budget allows, Then openrouter runs and cost is recorded | `test_runner.py` |
| Given budget exhausted, When all free fail, Then task fails without hitting claude | `test_runner.py` |
| Given invalid JSON response, When using StructuredLLM, Then correction prompt retries once | `test_structured_llm.py` |

### Coverage target

- Unit: ≥90% of `ai_agents/` (all branches of runner + cost_guard + registry parsing).
- E2E: one smoke per agent + one chain-fallback test. No more (CLAUDE.md: "balanced").

## Validation

A build is shippable when all four pass:

| Check | Command | Pass criteria |
|---|---|---|
| Install | `scripts/ai_agents/install_cli_tools.sh` | Installs codex/gemini/opencode via npm, prints auth steps, exits 0 |
| Unit | `.venv/bin/pytest tests/unit/ai_agents/ -q` | All pass; ≥90% coverage |
| E2E smoke | `E2E=1 pytest tests/e2e/ai_agents/test_codex_healthcheck.py tests/e2e/ai_agents/test_end_to_end_hello.py -q` | `hello.py` created; cost logged; duration < 2 min |
| Chain fallback | `E2E=1 pytest tests/e2e/ai_agents/test_chain_fallback.py` | Primary forced fail; next succeeds; both attempts logged |

`scripts/ai_agents/smoke_test.sh` wraps these — one command for the operator.

## Deliverables

### New files

```
ai_agents/__init__.py                ~30 LOC
ai_agents/base.py                    ~80 LOC
ai_agents/codex_agent.py             ~80 LOC
ai_agents/gemini_agent.py            ~80 LOC
ai_agents/opencode_agent.py         ~100 LOC
ai_agents/registry.py               ~120 LOC
ai_agents/runner.py                 ~100 LOC
ai_agents/cost_guard.py              ~80 LOC
ai_agents/structured_llm.py         ~160 LOC
ai_agents/tracing.py                 ~60 LOC
ai_agents/errors.py                  ~40 LOC
config/agents.yml                    ~30 LOC
scripts/ai_agents/requirements.txt   (adds: litellm>=1.83.0, instructor, langfuse, pydantic, pyyaml, python-dotenv)
scripts/ai_agents/install_cli_tools.sh ~40 LOC
scripts/ai_agents/setup_venv.sh      ~20 LOC
scripts/ai_agents/smoke_test.sh      ~30 LOC
tests/unit/ai_agents/                 7 files, ~400 LOC total
tests/e2e/ai_agents/                  6 files, ~200 LOC total
```

### Modified files

- `.env.example` — new keys: `COST_PER_TASK_USD`, `COST_PER_DAY_USD`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `AI_CODING_PRIORITY`, `AI_STRUCTURED_PRIORITY`.
- `.gitignore` — add `logs/`, `agents.local.yml` (reserved for future user-local overrides).
- `README.md` — short "AI Agent layer" section linking to this spec.

### No change

- `CLAUDE.md` — existing rules cover every behavior in this spec.

## Size & method budgets (CLAUDE.md rules 3-4)

| File | Est. | Limit |
|---|---|---|
| Largest (`structured_llm.py`) | 160 | 300 ✓ |
| Average module | ~80 | 300 ✓ |
| Every method | ≤20 lines | 20 ✓ |

## Pre-implementation prerequisite

The project directory is not a git repository yet. Before implementation begins:

1. `git init` at the project root
2. `gh repo create <owner>/auto_ai_agent_for_boards --private --source=. --push`
3. First commit = current state (README, CLAUDE.md, existing Trello slice, existing specs including this one).
4. Create feature branch: `git checkout -b feat/ai-agent-layer`
5. Implementation commits land on `feat/ai-agent-layer`; merged back to `main` once the four validation checks pass.

## Future work (explicitly deferred)

- Sub-project C: repo identification from `repos.md`.
- Sub-project D: per-task git workflow (branch, commit, merge main in, merge back if tests pass).
- Sub-project E: main orchestration loop (poll To Do → pick → identify repo → run agent → comment → move to To Review).
- Sub-project F: stuck/questions flow (Waiting for answers + 48h auto-answer).
- Parallel agents on one task (multi-agent voting / redundancy).
- Agent-specific prompt scaffolding (per-vendor system prompts, tool-use recipes).
- Streaming results to caller (today the log file is the progress channel).

## Cross-references

- **Sub-project map:** [`docs/superpowers/decomposition.md`](../decomposition.md) — index of all six sub-projects and their current status.
- **Sub-project A (Trello adapter):** [`2026-04-18-trello-board-cli-design.md`](2026-04-18-trello-board-cli-design.md) — already implemented. This spec reuses the `Board` ABC and the existing `.env`.
- **Repo-wide conventions:** [`CLAUDE.md`](../../../CLAUDE.md) — BDD, method/file size limits, security rules, `.env` secret handling. All rules in CLAUDE.md apply to this spec unless explicitly waived (none are).

## Appendix A — Non-negotiable user constraints

These are immutable inputs to the design. Future plan revisions must preserve every item below; if you think one needs to change, raise it with the user before rewriting the plan.

1. **Claude is last failover.** Coding and structured chains end with Claude (API, paid). Claude must not be the default primary in any shipped config.
2. **Subscription-first.** Free-tier subscription backends (Codex CLI, Gemini CLI) must be attempted before any paid API call in both chains.
3. **Config-driven extensibility.** Adding a new LLM is a YAML edit; new subclasses only when a vendor needs genuinely different behavior (new auth, new output format).
4. **Coding chain and structured-LLM chain are independently configurable.** They may share entries but must not be forced to share ordering.
5. **`LiteLLM >= 1.83.0`.** Pinned lower bound; the release closed a known security issue. Do not downgrade.
6. **License policy.** Dependencies must be MIT, Apache-2.0, or BSD. AGPL, SSPL, FSL (e.g., Crush), Elastic License 2.0 (e.g., Phoenix/Arize) are forbidden.
7. **No Claude subscription proxying.** Do not ship code that reuses a user's Claude Pro/Max OAuth token. Anthropic's ToS forbids this; Claude is only callable via the paid Anthropic API.

## Appendix B — Decision log

Brief record of the key trade-offs made during design; surface here so a future revision understands *why*, not just *what*.

| Decision | Alternatives considered | Rationale |
|---|---|---|
| **OpenCode** for API-based backends (OpenRouter, Claude) | aider, raw LiteLLM + custom agent loop, pi-mono | OpenCode (MIT, 145k★) supports 75+ providers via model string — one tool covers all current and future API backends without new code. Better JSON output than aider; doesn't need a separate tool-use loop like raw LiteLLM would. |
| **Subprocess** each CLI, no proxy layer | CLIProxyAPI, 9router, ccs (Go/TS proxies) | Proxies break Anthropic ToS (Feb 2026 ban on subscription-sharing) and are sustainability-risk. Subprocess keeps per-vendor auth native and symmetric. |
| **pi-mono skipped** | — | Initial source mischaracterized it as a router; verified it's a standalone coding agent (peer of aider). No orchestration layer to reuse. |
| **Crush skipped** | — | FSL license (source-available) violates the MIT/Apache/BSD rule. |
| **Three subclasses, four logical agents** | Four subclasses (separate `ClaudeAgent`, `OpenRouterAgent`) | `OpenCodeAgent(model=...)` parameterizes to serve both roles. Registry treats them as distinct agents (`openrouter`, `claude`) with different cost tiers. |
| **Vanilla JSON prompt** for `AgentStructuredLLM` (not vendor-specific structured-output features) — hardcoded in Python; `chat()` runs in an empty tempdir so no convention file pollutes non-code calls | Anthropic tool-use API, OpenAI JSON mode, convention-file-driven prompt | Keeps the abstraction portable across Codex/Gemini/OpenCode/LiteLLM; one prompt works everywhere. Retry-on-`ValidationError` covers the occasional parse failure. Coding path (`run()`) is separate — it relies on each CLI's native read of the target repo's convention file (`AGENTS.md` / `GEMINI.md`) with no injection or fallback from this library. |
| **`StructuredLLM` as ABC with three impls** | Single concrete class with if/else | User explicitly chose ABC so future impls (e.g. `OllamaStructuredLLM` for local) plug in without modifying the base. |
| **Langfuse** (optional, no-op without creds) | Helicone, Phoenix/Arize, no tracing | MIT core; first-class LiteLLM integration. Phoenix on Elastic License 2.0 violates license rule. |
| **`CostGuard` as the budget enforcer** | LiteLLM budget manager alone | LiteLLM only sees its own calls; OpenCode-subprocess cost needs to be parsed from OpenCode's JSON output. `CostGuard` covers both paths. Name changed from the earlier "LiteLLM budget" draft because LiteLLM isn't the canonical source of cost. |
| **Git worktree isolation deferred to sub-project D** | Build it into `AIAgent.run()` | Keeps the LLM layer pure; per-task branch/merge is a separate concern. |

## Appendix C — Sources

### Anthropic subscription proxying ban (Feb 2026)

- [Anthropic clarifies ban on third-party tool access to Claude — The Register, 2026-02-20](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access/)
- [Anthropic closes door on subscription use of OpenClaw — The Register, 2026-04-06](https://www.theregister.com/2026/04/06/anthropic_closes_door_on_subscription/)
- [Anthropic OAuth Policy Feb 2026: What Changed](https://aihackers.net/posts/anthropic-claude-code-oauth-policy-feb-2026/)
- [Agent SDK should support Max plan billing — Issue #559](https://github.com/anthropics/claude-agent-sdk-python/issues/559)

### Tools

- [OpenCode — anomalyco/opencode](https://github.com/anomalyco/opencode) · [docs](https://opencode.ai/docs/)
- [LiteLLM docs](https://docs.litellm.ai/) · [Langfuse + LiteLLM integration](https://langfuse.com/docs/integrations/litellm) · [LiteLLM budget manager](https://docs.litellm.ai/docs/budget_manager)
- [Codex CLI auth](https://developers.openai.com/codex/auth)
- [Gemini CLI auth](https://geminicli.com/docs/get-started/authentication/)
- [Langfuse (MIT core)](https://langfuse.com/) · [Instructor (MIT)](https://python.useinstructor.com/)

### Skipped-tool license notes

- [Crush (FSL-1.1-MIT / Charm License)](https://github.com/charmbracelet/crush) — source-available, not OSI-OSS.
- Phoenix / Arize uses Elastic License 2.0 — source-available, excluded by policy.
