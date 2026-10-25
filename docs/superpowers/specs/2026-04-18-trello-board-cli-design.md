# Trello Board Adapter + CLI — Design

**Date:** 2026-04-18
**Status:** Approved (in implementation)

## Goal

Two outcomes from one piece of work:

1. **Immediate:** a CLI command that creates a Trello card named `task` with the comment `test comment` in the user's "To Do" list.
2. **Foundational:** a reusable, provider-agnostic `Board` interface so the rest of the README's vision (pick from To Do → identify repo → implement → move to To Review with comment; move to Waiting for answers; 48h auto-answer) can be built on top without coupling to Trello specifically.

## Non-goals (YAGNI)

- Auto-answer-after-48h logic (needs Trello action history; defer until that feature is built)
- Fetching comments back from a card
- Attachments, members, labels, due dates
- Other board providers (Linear, Asana, GitHub Projects) — `Board` is designed to admit them later, not implemented now
- Webhooks / push updates (the agent will poll)

## Architecture

```
boards/                      # reusable, provider-agnostic Python package
├── __init__.py
├── board.py                 # Board ABC + Task dataclass
└── trello_board.py          # TrelloBoard(Board) — Trello REST adapter

scripts/trello/              # setup + thin CLI entrypoint
├── setup_venv.sh            # creates .venv, installs requirements
├── requirements.txt         # requests, python-dotenv
└── trello_cli.py            # CLI subcommands → TrelloBoard methods
```

`boards/` is the durable artifact: future agent code imports `from boards.trello_board import TrelloBoard` and calls methods on the abstraction. `scripts/trello/` is the operator-facing surface for setup, smoke-testing, and one-off operations.

### `Board` (abstract base)

| Method | Purpose | Used by future agent for |
|---|---|---|
| `get_lists() -> list[str]` | Names of all lists/columns on the board | Setup, debugging |
| `list_tasks(list_name) -> list[Task]` | Tasks currently in a column | "Pick from To Do" |
| `create_task(list_name, name, description="") -> Task` | Add a card to a column | Manual seeding (this CLI's job) |
| `move_task(task_id, target_list_name) -> None` | Move card to another column | "Move to To Review / Waiting for answers" |
| `add_comment(task_id, text) -> None` | Comment on a card | "Comment what was done / questions" |

`Task` is a dataclass: `id, name, description, list_name, url`. Plain values, no provider-specific objects leak through the interface.

### `TrelloBoard(Board)`

Implements all five methods against the Trello REST API.

- `__init__(api_key, token, board_id)` — stores credentials, prepares a `requests.Session`, initializes empty list-name → list-id cache
- `_request(method, path, params=None, json=None)` — internal helper that injects `key` + `token` into query params, raises on non-2xx with sanitized error (auth params stripped before logging), returns parsed JSON
- `_get_list_id(list_name)` — cached lookup; on cache miss fetches `/1/boards/{board_id}/lists` and rebuilds the cache; raises `ValueError` if name still not found

### `trello_cli.py` (operator surface)

Subcommands:

| Command | Behavior |
|---|---|
| `add-task --name X [--comment Y]` | Creates card in `$TRELLO_TO_DO_LIST_NAME`; if `--comment` given, adds it. Prints card URL. |
| `list-boards` | GET `/1/members/me/boards`; prints `id  name` per row. Setup/debug. |
| `list-tasks [--list NAME]` | Defaults to `$TRELLO_TO_DO_LIST_NAME`. Prints `id  name` per task. Smoke test. |

CLI loads `.env` from repo root (via `python-dotenv`), constructs `TrelloBoard(...)`, dispatches to the right method. Catches and pretty-prints `requests.HTTPError`. Non-zero exit on failure.

## Data flow — `add-task`

```
trello_cli.py add-task --name "task" --comment "test comment"
  → load .env (TRELLO_API_KEY, TRELLO_SECRET, TRELLO_BOARD_ID, TRELLO_TO_DO_LIST_NAME)
  → board = TrelloBoard(api_key, token, board_id)
  → task = board.create_task(to_do_list_name, "task")
       → _get_list_id("To Do")
            → cache miss → GET /1/boards/{board_id}/lists → cache populated → return id
       → POST /1/cards { idList, name } → returns card JSON → wrap as Task
  → board.add_comment(task.id, "test comment")
       → POST /1/cards/{task.id}/actions/comments { text }
  → print task.url
```

## Error handling

- Missing required env var → exit 2 with `"Required env var X not set"` (no values logged)
- HTTP non-2xx → raise `TrelloAPIError(status, sanitized_body)`; CLI catches and prints; exit 1
- List name not found → `ValueError("List 'X' not found on board. Available: [...]")`
- All `_request` log lines mask `key` and `token` in the URL/params before logging

## Security (CLAUDE.md rule 8)

- Secrets read from env vars only — never hardcoded, never accepted as CLI args (so they don't end up in shell history)
- `key` and `token` query params stripped from any URL/params before logging or error output
- `.env` already gitignored (will verify on scaffold; add `.gitignore` entry if missing)

## File-size & method-size budgets (CLAUDE.md rules 3-4)

| File | Estimate | Limit |
|---|---|---|
| `boards/board.py` | ~40 lines | 300 |
| `boards/trello_board.py` | ~150 lines | 300 |
| `scripts/trello/trello_cli.py` | ~80 lines | 300 |
| `scripts/trello/setup_venv.sh` | ~15 lines | 300 |

Every method ≤20 lines.

## Validation

The end-to-end test for this slice is the user's exact request, run live against Trello:

```
scripts/trello/setup_venv.sh
.venv/bin/python scripts/trello/trello_cli.py add-task --name "task" --comment "test comment"
.venv/bin/python scripts/trello/trello_cli.py list-tasks --list "$TRELLO_TO_DO_LIST_NAME"   # confirm card present
```

Unit tests on URL construction or env loading would be ceremony for a 250-line slice — skipped now. When the agent's main loop is built (next sub-project), tests against a mocked `Board` become the relevant test layer.

## Future work (explicitly deferred)

- `LinearBoard(Board)`, `GitHubProjectsBoard(Board)` — second & third providers, prove the abstraction holds
- `Board.get_task_age_in_list(task_id) -> timedelta` for the 48h auto-answer feature
- Agent main loop: poll → pick → identify repo → implement → comment → move
- Repo identification from `repos.md`
