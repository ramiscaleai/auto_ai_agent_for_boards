import logging

from boards.board import Board, Task

log = logging.getLogger(__name__)

_PREFIX = "[AI Agent] Questions about this task:\n\n"


def format_questions(questions: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
    return f"{_PREFIX}{numbered}"


class StuckHandler:
    def __init__(self, board: Board, waiting_list: str) -> None:
        self._board = board
        self._waiting = waiting_list

    def handle(self, task: Task, questions: list[str], board: Board | None = None, waiting_list: str | None = None) -> None:
        target_board = board or self._board
        target_waiting = waiting_list or self._waiting
        comment = format_questions(questions)
        target_board.add_comment(task.id, comment)
        target_board.move_task(task.id, target_waiting)
        log.info("Task %s moved to %r with %d question(s)", task.id, target_waiting, len(questions))
