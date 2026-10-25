# auto_ai_agent_for_boards

[![tests](https://github.com/ramiscaleai/auto_ai_agent_for_boards/actions/workflows/tests.yml/badge.svg)](https://github.com/ramiscaleai/auto_ai_agent_for_boards/actions/workflows/tests.yml)

An autonomous AI agent that picks tasks from a Trello board, implements them in the relevant git repo, and manages the full card lifecycle.

## What it does

1. **Polls** "To Do" column on a Trello board
2. **Identifies** the relevant repo(s) from `repos.md` using LLM matching
3. **Implements** the task using a coding agent (Codex → Gemini → OpenCode fallback chain)
4. **Commits** changes on a task branch, merges `main` in, merges back if green
5. **Moves** the card to "To Review" with a summary comment
6. **Gets stuck?** Posts questions as a comment and moves to "Waiting for answers". After 48h with no reply, auto-answers with LLM best-guess and re-queues.
7. Currently Trello is implemented and connected

## Quickstart

```bash
# 1. Install Python deps:
python3 -m venv .venv && .venv/bin/pip install -r scripts/orchestrator/requirements.txt

# 2. Install + validate all AI agents (installs missing, reports auth status):
./scripts/ai_agents/setup_agents.sh
# Follow any [!] / [✗] instructions it prints (codex login, gemini OAuth, .env keys)

# 3. Configure .env (copy .env.example and fill in values):
cp .env.example .env
# Edit: TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID, REPOS_MD_PATH

# 4. List your repos: copy repos.example.md to repos.md (git-ignored) and edit it

# 5. Start the agent:
.venv/bin/python main.py

# 6. Seed the curated top-30 backlog for this repo:
.venv/bin/python scripts/trello/trello_cli.py seed-current-repo-backlog
```

## Running as a systemd timer

For unattended operation on Linux hosts with systemd, install the included timer. The timer runs one poll iteration at a time and schedules the next run after the previous run finishes.

`sudo` is only required for `install.sh` (writes to `/etc/systemd/system/`). Once installed, the service and all agents (Codex, Gemini, etc.) run as your regular user with no elevated privileges. To add your user to sudoers: `su -c "usermod -aG sudo $USER"` then log out and back in.

```bash
# Optional: set AGENT_POLL_INTERVAL_MIN in .env first (default: 5 minutes)
sudo scripts/service/install.sh

# Check status
sudo systemctl status auto-ai-agent.timer     # next scheduled run
sudo systemctl status auto-ai-agent.service   # last run result

# Watch logs
journalctl -u auto-ai-agent.service -f

# Trigger a manual run immediately
sudo systemctl start auto-ai-agent.service

# Stop (prevents future runs)
sudo systemctl stop auto-ai-agent.timer
sudo systemctl disable auto-ai-agent.timer
sudo systemctl stop auto-ai-agent.service     # if a run is currently in progress
```

Set `AGENT_POLL_INTERVAL_MIN` in `.env` to change the timer interval. To remove the timer and service units without deleting code, logs, or `.env`, run:

```bash
sudo scripts/service/uninstall.sh
```

## Environment variables

See `.env.example` for all options. Key ones:

| Variable | Default | Description |
|---|---|---|
| `TRELLO_API_KEY` | required | Trello API key |
| `TRELLO_TOKEN` | required | Trello user token |
| `TRELLO_BOARD_ID` | required | Target board ID |
| `TRELLO_TO_DO_LIST_NAME` | `To Do` | Source column |
| `TRELLO_BACKLOG_LIST_NAME` | `Backlog` | List used by the backlog seeding CLI |
| `TRELLO_TO_REVIEW_LIST_NAME` | `To Review` | Done column |
| `TRELLO_WAITING_LIST_NAME` | `Waiting for answers` | Stuck column |
| `REPOS_MD_PATH` | `repos.md` | Path to repo registry |
| `POLL_INTERVAL_S` | `60` | Seconds between polls |
| `AGENT_POLL_INTERVAL_MIN` | `5` | Minutes between systemd timer runs |
| `CODEX_MODEL` | `gpt-5.5` | Model used by the default Codex coding agent |
| `CODEX_REASONING_EFFORT` | `xhigh` | Reasoning effort passed to Codex via `model_reasoning_effort` |
| `AUTO_ANSWER_HOURS` | `48` | Hours before auto-answering |
| `COST_PER_TASK_USD` | `0.50` | Per-task budget cap |
| `COST_PER_DAY_USD` | `5.00` | Daily budget cap |

The default coding chain is `codex, gemini, openrouter, claude`. For the first
slot, `CodexAgent` explicitly runs `gpt-5.5` with reasoning effort `xhigh`
unless overridden by `.env` or `config/agents.yml`.

## repos.md format

```markdown
## my-backend
path: /srv/repos/my-backend
description: Python FastAPI backend serving the REST API
tags: [python, api, database]
trello_board_id: 0123456789abcdef01234567

## my-frontend
path: /srv/repos/my-frontend
description: React SPA for end users
tags: [react, typescript, ui]
```

`trello_board_id` is optional. Per task, Trello board resolution is:

1. Use the target repo's `.env` when it contains `TRELLO_API_KEY`, `TRELLO_TOKEN`, and `TRELLO_BOARD_ID`.
2. Otherwise use that repo's optional `trello_board_id` from `repos.md`.
3. Otherwise fall back to this repo's Trello board from `auto_ai_agent_for_boards/.env`.

## Testing

```bash
# Unit tests (no external deps):
.venv/bin/python -m pytest tests/unit/ tests/e2e/git_workflow/

# Full E2E (requires codex + gemini authenticated):
E2E=1 .venv/bin/python -m pytest tests/e2e/
```

## Maintenance: opencode `$TMPDIR` leak

`opencode` is a Bun standalone binary that extracts its embedded native libs
into `$TMPDIR` on **every** launch and never deletes them — ~5.3 MiB per
`opencode run`, ~15 MiB for a full TUI init (a ~9.7 MiB OpenTUI lib + a ~5.3 MiB
audio lib). Any process that runs it with `TMPDIR` pointed at a shared agent temp
leaks one copy per call (~1.5 GiB/day observed). This is a deliberate workaround
for upstream Bun bug oven-sh/bun#30717 and is **not fixed by upgrading** —
opencode 1.17.8 (2026-06-17, latest) still leaks — so the only cures are a
private per-call `$TMPDIR` or the janitor below. `OpenCodeAgent` sandboxes
opencode under a throwaway `$TMPDIR` removed after each call, so this agent never
contributes to the leak.

As a backstop for *other* opencode callers on the host (any un-sandboxed interactive/`run`
caller that inherits a shared agent `TMPDIR` such as `/tmp/claude-$(id -u)`), each poll runs
`scripts/maintenance/clean_agent_tmp_leak.sh`, which deletes orphaned
`.<hash>.so` / `.<hash>.tmp` files and `opencode-tmp-*` dirs older than a grace
window (default **24h**, so a long-running opencode session's libs are never
pulled out from under it). Run it manually any time:

```bash
DRY_RUN=1 scripts/maintenance/clean_agent_tmp_leak.sh                 # preview
scripts/maintenance/clean_agent_tmp_leak.sh                           # clean (>24h old)
AGENT_TMP_ROOT=/tmp/claude-$(id -u) LEAK_MIN_AGE_MIN=0 scripts/maintenance/clean_agent_tmp_leak.sh
```

## Trello operator CLI

```bash
# Preview the curated backlog without creating cards:
.venv/bin/python scripts/trello/trello_cli.py seed-current-repo-backlog --dry-run

# Create the top 30 cards in the Backlog list:
.venv/bin/python scripts/trello/trello_cli.py seed-current-repo-backlog
```

## Architecture

| Package | Purpose |
|---|---|
| `boards/` | Board ABC + TrelloBoard REST adapter |
| `ai_agents/` | CodexAgent / GeminiAgent / OpenCodeAgent + registry, runner, cost guard |
| `repo_identifier/` | Parse repos.md + LLM-based task→repo matching |
| `git_workflow/` | TaskWorkspace: branch/commit/merge workflow |
| `orchestrator/` | Main poll loop + TaskRunner wiring everything together |
| `auto_answer/` | StuckHandler + AutoAnswerer (48h flow) |

Full sub-project map: [`docs/superpowers/decomposition.md`](docs/superpowers/decomposition.md)

## License

MIT, see [LICENSE](LICENSE).
