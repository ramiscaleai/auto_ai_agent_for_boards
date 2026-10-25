from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel


@dataclass(frozen=True)
class RepoEntry:
    name: str
    path: Path
    description: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    trello_board_id: str | None = None

    def summary(self) -> str:
        tags = ", ".join(self.tags) if self.tags else "—"
        board = self.trello_board_id or "—"
        return f"[{self.name}] path={self.path}  tags={tags}  trello_board_id={board}\n  {self.description}"


class RepoMatch(BaseModel):
    names: list[str]
    rationale: str


@dataclass(frozen=True)
class RepoSelection:
    repos: tuple[RepoEntry, ...]
    rationale: str
