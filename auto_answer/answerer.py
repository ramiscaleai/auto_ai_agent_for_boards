import logging
from datetime import datetime, timezone

from pydantic import BaseModel

from ai_agents import StructuredLLM
from boards.board import Board, Task

from .stuck_handler import _PREFIX

log = logging.getLogger(__name__)

_ANSWER_PROMPT = """\
You are an experienced software engineer auto-answering questions about an unblocked task.
Use best practices, common sense, and patterns from similar products.
Be concise and decisive — the agent will use your answers to continue implementing.

Task: {name}
Description: {description}

Questions:
{questions}

Provide clear, actionable answers to each question above.
"""


class AutoAnswers(BaseModel):
    answers: str


class AutoAnswerer:
    def __init__(
        self,
        board: Board,
        waiting_list: str,
        to_do_list: str,
        auto_answer_hours: int,
        llm: StructuredLLM,
    ) -> None:
        self._board = board
        self._waiting = waiting_list
        self._todo = to_do_list
        self._threshold_s = auto_answer_hours * 3600
        self._llm = llm

    def check_and_answer(self) -> int:
        tasks = self._board.list_tasks(self._waiting)
        answered = 0
        for task in tasks:
            if self._is_overdue(task):
                self._answer(task)
                answered += 1
        return answered

    def _is_overdue(self, task: Task) -> bool:
        entry = self._board.get_list_entry_time(task.id)
        entry_utc = entry.replace(tzinfo=timezone.utc) if entry.tzinfo is None else entry
        age_s = (datetime.now(timezone.utc) - entry_utc).total_seconds()
        return age_s >= self._threshold_s

    def _answer(self, task: Task) -> None:
        questions = self._extract_questions(task)
        if not questions:
            log.warning("No questions found for waiting task %s — re-queuing anyway", task.id)
            self._board.move_task(task.id, self._todo)
            return
        prompt = _ANSWER_PROMPT.format(
            name=task.name, description=task.description or "(none)", questions=questions
        )
        result: AutoAnswers = self._llm.ask(prompt, AutoAnswers)
        comment = f"[AI Agent] Auto-answer after 48h:\n\n{result.answers}"
        self._board.add_comment(task.id, comment)
        self._board.move_task(task.id, self._todo)
        log.info("Auto-answered task %s — moved back to %r", task.id, self._todo)

    def _extract_questions(self, task: Task) -> str:
        comments = self._board.get_comments(task.id)
        for comment in reversed(comments):
            if comment.text.startswith(_PREFIX):
                return comment.text[len(_PREFIX):].strip()
        return ""
