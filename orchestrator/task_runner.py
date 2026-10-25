import logging
from dataclasses import dataclass
from typing import Literal

from ai_agents import AgentRunner, AgentTask, AgentResult
from boards.backlog_seed_intent import SeedIntent, parse_seed_intent
from boards.board import Board, Task
from boards.repo_backlog_seeder import RepoBacklogSeeder, SeedOutcome
from git_workflow import BranchNamer, MergeConflictError, TaskWorkspace
from repo_identifier import RepoIdentifier
from repo_identifier.models import RepoEntry

from .prompt import RepoContext, build_prompt
from .trello_resolver import ResolvedTrelloBoard, TrelloBoardResolver

log = logging.getLogger(__name__)

TaskStatus = Literal["done", "questions", "failed", "conflict"]


@dataclass
class TaskOutcome:
    status: TaskStatus
    result: AgentResult
    error: str | None = None
    resolved_board: Board | None = None
    resolved_task: Task | None = None
    waiting_list: str | None = None


class TaskRunner:
    def __init__(
        self,
        board: Board,
        identifier: RepoIdentifier,
        runner: AgentRunner,
        branch_namer: BranchNamer,
        to_review_list: str,
        waiting_list: str = "Waiting for answers",
        agent_timeout_s: int = 1800,
        prompt_comment_budget_bytes: int = 16_000,
        trello_resolver: TrelloBoardResolver | None = None,
        backlog_seeder: RepoBacklogSeeder | None = None,
    ) -> None:
        self._board = board
        self._identifier = identifier
        self._runner = runner
        self._namer = branch_namer
        self._to_review = to_review_list
        self._waiting = waiting_list
        self._agent_timeout_s = agent_timeout_s
        self._prompt_comment_budget_bytes = prompt_comment_budget_bytes
        self._trello_resolver = trello_resolver
        self._backlog_seeder = backlog_seeder

    def run(self, task: Task) -> TaskOutcome:
        log.info("Running task %s: %r", task.id, task.name)
        selection = self._identifier.identify_selection(f"{task.name}\n{task.description}")
        repos = list(selection.repos)
        repo = repos[0]
        repo_path = repo.path
        trello_target = self._resolve_board(repo)

        intent = parse_seed_intent(task.name, task.description)
        if intent is not None and self._backlog_seeder is not None:
            return self._run_seed(task, repo, intent, trello_target)

        comments = trello_target.board.get_comments(task.id)

        branch_name = self._namer.name(task.name, task.id)
        log.info("Branch name for task %s: %s", task.id, branch_name)
        with TaskWorkspace(repo_path, task.id, branch_name=branch_name) as ws:
            prompt = build_prompt(
                task,
                comments=comments,
                repo_context=RepoContext(
                    repos=tuple(repos),
                    rationale=selection.rationale,
                    current_branch=ws.branch,
                ),
                comment_budget_bytes=self._prompt_comment_budget_bytes,
            )
            result = self._runner.run(AgentTask(prompt=prompt, cwd=ws.cwd, timeout_s=self._agent_timeout_s))
            ws.stage_and_commit(f"agent: {task.name[:60]}")

            if result.questions:
                log.info("Task %s has questions — deferring to auto-answer flow", task.id)
                return TaskOutcome(
                    status="questions",
                    result=result,
                    resolved_board=trello_target.board,
                    resolved_task=task,
                    waiting_list=trello_target.waiting_list,
                )

            return self._finish(task, ws, result, trello_target)

    def _finish(
        self,
        task: Task,
        ws: TaskWorkspace,
        result: AgentResult,
        trello_target: ResolvedTrelloBoard,
    ) -> TaskOutcome:
        board = trello_target.board
        if not result.success:
            msg = f"Agent failed: {result.error or result.summary}"
            board.add_comment(task.id, msg)
            log.error("Task %s failed: %s", task.id, msg)
            return TaskOutcome(status="failed", result=result, error=msg, resolved_board=board, resolved_task=task)

        try:
            ws.merge_main_in()
            ws.merge_back_to_main()
        except MergeConflictError as exc:
            board.add_comment(task.id, f"Merge conflict: {exc}")
            log.error("Task %s merge conflict: %s", task.id, exc)
            return TaskOutcome(status="conflict", result=result, error=str(exc), resolved_board=board, resolved_task=task)

        summary = result.summary or "Task implemented successfully."
        board.add_comment(task.id, summary)
        board.move_task(task.id, trello_target.to_review_list)
        log.info("Task %s done — moved to %r via %s", task.id, trello_target.to_review_list, trello_target.source)
        return TaskOutcome(status="done", result=result, resolved_board=board, resolved_task=task)

    def _resolve_board(self, repo: RepoEntry) -> ResolvedTrelloBoard:
        if self._trello_resolver is None:
            return ResolvedTrelloBoard(
                board=self._board,
                to_do_list="",
                to_review_list=self._to_review,
                waiting_list=self._waiting,
                source="legacy",
            )
        return self._trello_resolver.resolve(repo)

    def _run_seed(
        self,
        task: Task,
        repo: RepoEntry,
        intent: SeedIntent,
        trello_target: ResolvedTrelloBoard,
    ) -> TaskOutcome:
        assert self._backlog_seeder is not None
        board = trello_target.board
        backlog_list = trello_target.backlog_list
        log.info(
            "Task %s classified as backlog-seed intent (count=%d, repo=%s, list=%s)",
            task.id, intent.count, repo.name, backlog_list,
        )
        outcome = self._backlog_seeder.seed(repo, intent, board, backlog_list)
        comment = _format_seed_comment(repo, intent, outcome, backlog_list)
        board.add_comment(task.id, comment)
        if not outcome.success:
            msg = outcome.reason or (
                f"Only {len(outcome.created)} of {intent.count} cards landed; "
                "leaving task in place for review."
            )
            log.error("Task %s seed failed: %s", task.id, msg)
            return TaskOutcome(
                status="failed",
                result=_agent_result_from_seed(outcome, success=False, error=msg),
                error=msg,
                resolved_board=board,
                resolved_task=task,
            )
        board.move_task(task.id, trello_target.to_review_list)
        log.info(
            "Task %s seeded %d cards in %r — moved to %r",
            task.id, len(outcome.created), backlog_list, trello_target.to_review_list,
        )
        return TaskOutcome(
            status="done",
            result=_agent_result_from_seed(outcome, success=True),
            resolved_board=board,
            resolved_task=task,
        )


def _format_seed_comment(repo: RepoEntry, intent: SeedIntent, outcome: SeedOutcome, backlog_list: str) -> str:
    header = (
        f"Seeded {len(outcome.created)}/{intent.count} new backlog cards for `{repo.name}` "
        f"into list `{backlog_list}` "
        f"(skipped {len(outcome.skipped_existing)} existing titles)."
    )
    constraints = (
        f"Constraints: min_backend={intent.min_backend}, min_frontend={intent.min_frontend}, "
        f"frontend_excludes_trello={intent.frontend_excludes_trello}."
    )
    samples = "\n".join(f"- {name}" for name in outcome.created[:10])
    body = [header, constraints]
    if samples:
        body.append(f"First created cards:\n{samples}")
    if outcome.reason:
        body.append(f"Note: {outcome.reason}")
    return "\n\n".join(body)


def _agent_result_from_seed(outcome: SeedOutcome, *, success: bool, error: str | None = None) -> AgentResult:
    return AgentResult(
        success=success,
        summary=outcome.summary(),
        files_changed=[],
        output=outcome.summary(),
        cost_usd=None,
        duration_s=0.0,
        error=error,
    )
