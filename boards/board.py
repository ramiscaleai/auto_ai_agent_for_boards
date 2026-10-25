from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ChecklistItem:
    name: str
    checked: bool


@dataclass(frozen=True)
class Attachment:
    name: str
    url: str


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    description: str
    list_name: str
    url: str
    labels: tuple[str, ...] = ()
    due_at: datetime | None = None
    checklist_items: tuple[ChecklistItem, ...] = ()
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class Comment:
    id: str
    author: str
    text: str
    created_at: datetime


class Board(ABC):
    """Provider-agnostic board interface (Trello, Linear, GitHub Projects, ...)."""

    @abstractmethod
    def get_lists(self) -> list[str]:
        """Return names of all lists/columns on the board."""

    @abstractmethod
    def list_tasks(self, list_name: str) -> list[Task]:
        """Return tasks currently in the named list."""

    @abstractmethod
    def create_task(self, list_name: str, name: str, description: str = "") -> Task:
        """Create a task in the named list and return it."""

    @abstractmethod
    def move_task(self, task_id: str, target_list_name: str) -> None:
        """Move a task to the named list."""

    @abstractmethod
    def add_comment(self, task_id: str, text: str) -> None:
        """Add a comment to a task."""

    @abstractmethod
    def get_comments(self, task_id: str) -> list[Comment]:
        """Return all comments on a task, oldest first."""

    @abstractmethod
    def get_list_entry_time(self, task_id: str) -> datetime:
        """Return when the task was last moved into its current list (UTC)."""
