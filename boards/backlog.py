from dataclasses import dataclass
from typing import Sequence

from boards.board import Board


@dataclass(frozen=True)
class BacklogTaskTemplate:
    title: str
    area: str
    impact: str
    repo_fit: str
    acceptance_criteria: tuple[str, ...]

    @property
    def card_name(self) -> str:
        return f"[{self.area}] {self.title}"

    @property
    def card_description(self) -> str:
        criteria = "\n".join(f"- {item}" for item in self.acceptance_criteria)
        return (
            f"Impact\n{self.impact}\n\n"
            f"Why this repo\n{self.repo_fit}\n\n"
            f"Acceptance criteria\n{criteria}"
        )


@dataclass(frozen=True)
class SeedResult:
    created: tuple[str, ...]
    skipped: tuple[str, ...]


def current_repo_backlog() -> tuple[BacklogTaskTemplate, ...]:
    tasks = (
        BacklogTaskTemplate(
            title="Claim cards before execution to prevent duplicate workers",
            area="Backend",
            impact="Removes the highest-risk race condition when more than one agent loop or timer fires at once.",
            repo_fit="The orchestrator currently picks the first To Do card with no claim or lease protocol, so concurrent runs can process the same work item twice.",
            acceptance_criteria=(
                "Introduce a claim or lease step before task execution starts.",
                "Skip cards already claimed by another active worker.",
                "Cover the concurrency path with unit or e2e tests.",
            ),
        ),
        BacklogTaskTemplate(
            title="Persist task run history in SQLite",
            area="Backend",
            impact="Gives the operator durable visibility into outcomes, durations, costs, and failures across runs.",
            repo_fit="The project currently logs outcomes but does not keep a queryable execution history for debugging or reporting.",
            acceptance_criteria=(
                "Store task id, repo, agent, status, duration, and cost for each run.",
                "Persist failure summaries and question outcomes.",
                "Expose a small read API or helper for later reporting features.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add retry and backoff for transient board and LLM failures",
            area="Backend",
            impact="Reduces noisy failed runs caused by short-lived API outages and rate limits.",
            repo_fit="Trello calls and agent subprocess work currently fail fast, which is brittle for unattended automation.",
            acceptance_criteria=(
                "Classify retryable failures separately from permanent ones.",
                "Apply bounded exponential backoff with logging.",
                "Avoid retrying non-idempotent steps after success is already recorded.",
            ),
        ),
        BacklogTaskTemplate(
            title="Route research and docs tasks away from coding agents by default",
            area="Backend",
            impact="Improves output quality and lowers spend by choosing the right workflow for non-coding work.",
            repo_fit="The repository already has structured LLM helpers, but the main runner still assumes every card should go through a code-editing agent.",
            acceptance_criteria=(
                "Classify tasks into coding versus non-coding modes.",
                "Use a lighter-weight path for research, planning, and content tasks.",
                "Keep the fallback chain for true implementation work.",
            ),
        ),
        BacklogTaskTemplate(
            title="Recover cleanly from interrupted task branches",
            area="Backend",
            impact="Prevents half-finished branches and stale worktrees from blocking later automation runs.",
            repo_fit="TaskWorkspace creates and merges branches, but interrupted runs can still leave the repo in a confusing state.",
            acceptance_criteria=(
                "Detect stale task branches and unfinished merges.",
                "Add a safe recovery path before new execution begins.",
                "Preserve user changes instead of force-resetting the repo.",
            ),
        ),
        BacklogTaskTemplate(
            title="Capture per-run artifacts for prompts, stdout, stderr, and diffs",
            area="Backend",
            impact="Makes failed runs debuggable without scraping transient console logs.",
            repo_fit="The agent layer reports status, but operators cannot inspect a structured artifact bundle after the fact.",
            acceptance_criteria=(
                "Write artifacts into a predictable run directory.",
                "Include prompt text, agent output, git diff summary, and failure metadata.",
                "Redact secrets before persisting artifacts.",
            ),
        ),
        BacklogTaskTemplate(
            title="Redact secrets from logs, comments, and saved prompts",
            area="Backend",
            impact="Closes an obvious security gap before the system handles more repos and more credentials.",
            repo_fit="The app uses board tokens, API keys, and prompt content that can easily leak through logs or task comments if not sanitized centrally.",
            acceptance_criteria=(
                "Implement shared redaction for known secret patterns and configured values.",
                "Apply redaction to logs, persisted artifacts, and board comments.",
                "Add tests that prove raw secrets are not emitted.",
            ),
        ),
        BacklogTaskTemplate(
            title="Expose a machine-readable health snapshot",
            area="Backend",
            impact="Makes systemd timers, smoke checks, and future dashboards observability-friendly.",
            repo_fit="There is no lightweight status endpoint or command that reports board reachability, agent availability, and last-run state in one place.",
            acceptance_criteria=(
                "Return JSON with board connectivity, repo registry status, and agent readiness.",
                "Include last successful run timestamp and current failure state.",
                "Keep the command cheap enough for frequent monitoring.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add startup validation for agent CLIs and authentication",
            area="Backend",
            impact="Turns late runtime failures into immediate actionable setup errors.",
            repo_fit="The repo ships setup scripts, but the main app still discovers missing tools or expired auth only after work has already started.",
            acceptance_criteria=(
                "Validate required CLIs and board credentials during startup.",
                "Report missing auth with precise remediation messages.",
                "Fail fast before claiming a task when prerequisites are broken.",
            ),
        ),
        BacklogTaskTemplate(
            title="Support per-repo execution policies and tool limits",
            area="Backend",
            impact="Lets the orchestrator treat production repos, docs repos, and experimental repos differently and more safely.",
            repo_fit="The project already maps tasks to repos, but all repos currently inherit the same workflow and risk profile.",
            acceptance_criteria=(
                "Add per-repo settings for timeouts, allowed tools, and merge behavior.",
                "Load settings from configuration instead of hard-coding them.",
                "Cover at least one repo override in tests.",
            ),
        ),
        BacklogTaskTemplate(
            title="Improve multi-repo routing with confidence scoring",
            area="Backend",
            impact="Reduces incorrect repo selection for cross-cutting tasks and makes operator review easier.",
            repo_fit="The identifier can return relevant repos, but it does not provide confidence or a clear way to handle ambiguous matches.",
            acceptance_criteria=(
                "Return ranked repo matches with a confidence value or rationale.",
                "Handle low-confidence matches with a safer fallback path.",
                "Add tests for ambiguous backend versus frontend tasks.",
            ),
        ),
        BacklogTaskTemplate(
            title="Implement bounded rebase-and-retry after merge conflicts",
            area="Backend",
            impact="Raises automation success rate for active repos without hiding real conflicts forever.",
            repo_fit="Task execution currently stops on merge conflicts instead of attempting a controlled retry on a refreshed branch.",
            acceptance_criteria=(
                "Retry a small number of times after updating from main.",
                "Record conflict summaries for operator review when retries fail.",
                "Avoid infinite loops and unsafe conflict resolution.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add provider contract tests for board implementations",
            area="Backend",
            impact="Makes future board integrations safer by enforcing shared behavior through one reusable test suite.",
            repo_fit="The board abstraction exists, but only the Trello implementation is exercised directly today.",
            acceptance_criteria=(
                "Create a reusable contract test suite for Board implementations.",
                "Run the suite against Trello and any test doubles.",
                "Cover comments, list moves, card creation, and timestamps.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add a webhook ingestion path alongside polling",
            area="Backend",
            impact="Makes the system responsive without relying solely on short polling intervals.",
            repo_fit="The current loop is poll-based only, which is simple but inefficient and slower than necessary for real operator workflows.",
            acceptance_criteria=(
                "Accept signed board events and queue eligible work.",
                "Keep polling as a fallback when webhooks are unavailable.",
                "Document deployment and local development behavior.",
            ),
        ),
        BacklogTaskTemplate(
            title="Build a local operator dashboard for queue and run status",
            area="Frontend",
            impact="Gives the project a usable operations surface instead of forcing everything through logs and another board tool.",
            repo_fit="Operators currently have no native interface for current activity, recent outcomes, or blocked runs inside this repo.",
            acceptance_criteria=(
                "Show queue counts, active task state, and recent outcomes.",
                "Render from local app data rather than embedding another board tool.",
                "Work on desktop and mobile widths.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add a run detail page with logs, artifacts, and git summary",
            area="Frontend",
            impact="Makes postmortems and operator review practical for real failed runs.",
            repo_fit="Once run history and artifacts exist, the next gap is a readable interface for inspecting one execution end to end.",
            acceptance_criteria=(
                "Display prompt, agent output, artifacts, and changed files for a selected run.",
                "Highlight failure reasons and unanswered questions.",
                "Keep long logs readable with filters or sections.",
            ),
        ),
        BacklogTaskTemplate(
            title="Create a repo registry editor instead of hand-editing repos.md",
            area="Frontend",
            impact="Lowers the barrier to keeping repo metadata accurate as the automation expands.",
            repo_fit="Repo registration is a core workflow, but today it requires manual markdown edits that are easy to break.",
            acceptance_criteria=(
                "Allow create, edit, validate, and reorder operations for repo entries.",
                "Preview the generated markdown before save.",
                "Surface schema validation errors inline.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add a task routing inspector UI",
            area="Frontend",
            impact="Helps operators understand why a task mapped to a repo or execution mode before the agent starts work.",
            repo_fit="The project already performs routing and classification, but there is no human-friendly interface for reviewing those decisions.",
            acceptance_criteria=(
                "Show routing rationale, confidence, and selected repo list.",
                "Preview the generated prompt and execution settings.",
                "Allow dry-run inspection without starting an agent.",
            ),
        ),
        BacklogTaskTemplate(
            title="Build a waiting-questions review screen",
            area="Frontend",
            impact="Makes blocked work manageable without scanning comments manually.",
            repo_fit="The waiting-for-answers flow exists, but there is no native way to review open questions or aging blocked tasks in this repo.",
            acceptance_criteria=(
                "List blocked tasks with age, repo, and extracted questions.",
                "Highlight items nearing the auto-answer threshold.",
                "Link directly to the relevant run and task context.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add spend and throughput charts for operators",
            area="Frontend",
            impact="Makes cost guard behavior and productivity trends visible enough to tune the system rationally.",
            repo_fit="The backend already tracks costs conceptually, but operators cannot visualize spend by day, agent, or repo.",
            acceptance_criteria=(
                "Graph daily spend, task counts, durations, and success rate.",
                "Filter by repo and agent provider.",
                "Handle empty and low-volume datasets cleanly.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add a setup status page for environment and auth checks",
            area="Frontend",
            impact="Turns onboarding and maintenance into a visible checklist instead of a shell-only workflow.",
            repo_fit="This repo relies on many external tools and secrets, which is difficult to verify quickly without a single status view.",
            acceptance_criteria=(
                "Show readiness for board access, agent CLIs, and required environment values.",
                "Display actionable remediation guidance for failed checks.",
                "Avoid revealing raw secret values in the UI.",
            ),
        ),
        BacklogTaskTemplate(
            title="Package the app as an installable CLI tool",
            area="DevEx",
            impact="Simplifies setup and makes local development, CI, and deployment more repeatable.",
            repo_fit="The repo still depends on ad hoc script entrypoints and manual path handling instead of a first-class package install.",
            acceptance_criteria=(
                "Provide a clean install path with console entrypoints.",
                "Keep the existing scripts working or document the migration.",
                "Verify the package install in CI or tests.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add a formal config schema with validation errors",
            area="Backend",
            impact="Prevents misconfiguration from surfacing as scattered runtime exceptions.",
            repo_fit="Configuration is spread across env vars and YAML with only partial validation today.",
            acceptance_criteria=(
                "Define a single validated config model for env and file-based settings.",
                "Produce field-specific errors with defaults where appropriate.",
                "Update tests for invalid and missing config cases.",
            ),
        ),
        BacklogTaskTemplate(
            title="Create a deterministic dry-run mode for the full orchestration loop",
            area="Backend",
            impact="Enables safe rehearsal of routing, prompt generation, and git workflow before touching real repos or boards.",
            repo_fit="The existing stack is hard to demo or validate end to end without making real external changes.",
            acceptance_criteria=(
                "Run through selection, routing, and prompt building without modifying external systems.",
                "Emit a clear execution plan for what would happen.",
                "Support tests and local operator debugging.",
            ),
        ),
        BacklogTaskTemplate(
            title="Parallelize safe background work such as repo identification and preflight checks",
            area="Backend",
            impact="Cuts task startup latency without overlapping unsafe git mutations.",
            repo_fit="The current flow is mostly serial even for independent steps that could run concurrently.",
            acceptance_criteria=(
                "Identify which startup steps can run safely in parallel.",
                "Keep git writes and board mutations serialized.",
                "Measure the latency improvement in tests or logs.",
            ),
        ),
        BacklogTaskTemplate(
            title="Generate richer completion summaries with changed files and validation results",
            area="Backend",
            impact="Improves review quality and reduces the need to inspect every branch manually.",
            repo_fit="TaskRunner comments completed work back to the board, but the summary is still thin for meaningful code review.",
            acceptance_criteria=(
                "Include changed files, test results, and notable risks in the completion comment.",
                "Keep summaries concise enough for board consumption.",
                "Cover the formatting in tests.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add CI to run unit tests, shell linting, and targeted e2e smoke checks",
            area="DevEx",
            impact="Catches regressions before they reach the unattended automation loop.",
            repo_fit="The repo has a meaningful test suite but no visible automated validation path in version control workflows.",
            acceptance_criteria=(
                "Run unit tests and bash validation on every push or pull request.",
                "Gate heavier e2e checks behind a deliberate trigger or secret availability.",
                "Publish failures clearly enough for contributors to act on them.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add fixture-driven end-to-end tests for realistic board lifecycles",
            area="Backend",
            impact="Raises confidence in orchestration changes without requiring every test run to hit a live board.",
            repo_fit="There is one real Trello e2e path, but the project still lacks broad scenario coverage for lifecycle edge cases.",
            acceptance_criteria=(
                "Model success, blocked, retry, and merge-conflict flows with realistic fixtures.",
                "Keep tests deterministic and fast enough for regular CI use.",
                "Preserve one live-board smoke test for integration confidence.",
            ),
        ),
        BacklogTaskTemplate(
            title="Support a local web UI for manual task submission and run triggering",
            area="Frontend",
            impact="Lets operators test and use the automation even when they do not want to create board cards first.",
            repo_fit="A native control surface is the obvious next step once the automation core exists, and it should not depend on another board interface.",
            acceptance_criteria=(
                "Allow operators to submit a task description and target repo manually.",
                "Show the generated plan before execution starts.",
                "Reuse the same backend orchestration primitives as board-driven runs.",
            ),
        ),
        BacklogTaskTemplate(
            title="Add rate-limit aware scheduling across agent providers",
            area="Backend",
            impact="Prevents thrashing when one provider slows down or starts rejecting requests.",
            repo_fit="The fallback chain exists, but there is no scheduler intelligence around provider health or temporary rate limits.",
            acceptance_criteria=(
                "Track recent provider failures and cooldown windows.",
                "Prefer healthy providers without violating configured priority.",
                "Log why a provider was skipped or retried.",
            ),
        ),
    )
    _validate_backlog(tasks)
    return tasks


def seed_backlog(
    board: Board,
    list_name: str,
    tasks: Sequence[BacklogTaskTemplate] | None = None,
    *,
    dry_run: bool = False,
) -> SeedResult:
    templates = tuple(tasks or current_repo_backlog())
    _validate_backlog(templates)
    existing_names = {task.name for task in board.list_tasks(list_name)}
    created: list[str] = []
    skipped: list[str] = []
    for template in templates:
        card_name = template.card_name
        if card_name in existing_names:
            skipped.append(card_name)
            continue
        if not dry_run:
            board.create_task(list_name, card_name, template.card_description)
        existing_names.add(card_name)
        created.append(card_name)
    return SeedResult(created=tuple(created), skipped=tuple(skipped))


def _validate_backlog(tasks: Sequence[BacklogTaskTemplate]) -> None:
    if len(tasks) != 30:
        raise ValueError(f"Expected exactly 30 backlog tasks, got {len(tasks)}")
    titles = [task.card_name for task in tasks]
    if len(titles) != len(set(titles)):
        raise ValueError("Backlog task names must be unique")
    backend_count = sum(task.area == "Backend" for task in tasks)
    frontend_count = sum(task.area == "Frontend" for task in tasks)
    if backend_count < 10:
        raise ValueError(f"Expected at least 10 backend tasks, got {backend_count}")
    if frontend_count < 5:
        raise ValueError(f"Expected at least 5 frontend tasks, got {frontend_count}")
    frontend_mentions_trello = [
        task.card_name for task in tasks if task.area == "Frontend" and "trello" in task.card_description.lower()
    ]
    if frontend_mentions_trello:
        raise ValueError(f"Frontend tasks must not target Trello UI work: {frontend_mentions_trello}")
