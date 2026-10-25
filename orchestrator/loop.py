import logging
import time
from typing import TYPE_CHECKING

from boards.board import Board

from .task_runner import TaskRunner

if TYPE_CHECKING:
    from auto_answer import AutoAnswerer, StuckHandler

log = logging.getLogger(__name__)


class OrchestratorLoop:
    def __init__(
        self,
        board: Board,
        task_runner: TaskRunner,
        to_do_list: str,
        poll_interval_s: int = 60,
        stuck_handler: "StuckHandler | None" = None,
        auto_answerer: "AutoAnswerer | None" = None,
    ) -> None:
        self._board = board
        self._task_runner = task_runner
        self._to_do = to_do_list
        self._interval = poll_interval_s
        self._stuck = stuck_handler
        self._answerer = auto_answerer

    def run_once(self) -> bool:
        """Pick and run one task. Returns True if a task was processed."""
        if self._answerer:
            self._answerer.check_and_answer()

        tasks = self._board.list_tasks(self._to_do)
        if not tasks:
            log.info("No tasks in %r — sleeping", self._to_do)
            return False

        task = tasks[0]
        log.info("Picked task %s: %r", task.id, task.name)
        outcome = self._task_runner.run(task)
        log.info("Task %s outcome: %s", task.id, outcome.status)

        if outcome.status == "questions" and self._stuck and outcome.result.questions:
            self._stuck.handle(
                outcome.resolved_task or task,
                outcome.result.questions,
                board=outcome.resolved_board,
                waiting_list=outcome.waiting_list,
            )
        return True

    def run_forever(self) -> None:
        log.info("OrchestratorLoop starting — polling %r every %ds", self._to_do, self._interval)
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("Unhandled error in orchestrator loop")
            time.sleep(self._interval)
