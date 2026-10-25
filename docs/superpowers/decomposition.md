# Project decomposition — auto_ai_agent_for_boards

The README describes a vision too large for one spec. The work splits into six independent sub-projects. Each sub-project gets its own design spec, implementation plan, and feature branch.

## Sub-project index

| # | Name | Purpose | Status | Spec |
|---|---|---|---|---|
| **A** | Trello board adapter | Provider-agnostic `Board` ABC + `TrelloBoard` REST adapter + operator CLI | ✅ Done | [2026-04-18-trello-board-cli-design.md](specs/2026-04-18-trello-board-cli-design.md) |
| **B** | AI Agent layer | `AIAgent` ABC + `CodexAgent` / `GeminiAgent` / `OpenCodeAgent` subclasses; registry + priority-chain fallback; `StructuredLLM`; `CostGuard`; Langfuse | ✅ Done | [2026-04-18-ai-agent-layer-design.md](specs/2026-04-18-ai-agent-layer-design.md) |
| **C** | Repo identification | Parse `repos.md`; map a task description to one-or-more repo paths | ✅ Done | — |
| **D** | Per-task git workflow | Branch creation, commit cadence, merge-main-in, merge-back-on-green | ✅ Done | — |
| **E** | Main orchestration loop | Poll "To Do" → pick task → identify repo (C) → run agent (B+D) → comment → move to "To Review" | ✅ Done | — |
| **F** | Stuck + auto-answer flow | Questions detected → comment + move to "Waiting" → after 48h auto-answer with LLM + re-queue | ✅ Done | — |

## Dependency graph

```
A (Trello)  ─┐
             ├─▶ E (Main loop) ─▶ F (Stuck flow)
B (AI agents)─┤
             ├─▶ D (Git workflow) ─┐
C (Repos.md) ─┘                    └─▶ E
```

- A, B, C are leaf sub-projects — independently buildable and testable.
- D depends on B (the agent needs a workspace to edit).
- E is the integrator — ties A, B, C, D together into the autonomous loop.
- F extends E with the questions/answer flow.

## Build order (recommended)

1. **A** — done.
2. **B** — next (current spec).
3. **C** — small, can interleave with D.
4. **D** — depends on B being stable.
5. **E** — needs A, B, C, D.
6. **F** — needs E; defer until the basic loop runs reliably.

## Pre-implementation prerequisite (all sub-projects)

The project directory is not yet a git repository. Before any sub-project's implementation commits start, complete the one-time setup:

1. `git init` at the project root
2. `gh repo create <owner>/auto_ai_agent_for_boards --private --source=. --push`
3. First commit = current state — existing code, all specs in `docs/superpowers/specs/`, this decomposition doc.
4. Each sub-project from then on = one feature branch → merged back when its validation checks pass.
