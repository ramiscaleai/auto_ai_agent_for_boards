import logging
import re
from pathlib import Path

from .models import RepoEntry

log = logging.getLogger(__name__)

_PATH_RE = re.compile(r"^path:\s*(.+)$", re.MULTILINE)
_DESC_RE = re.compile(r"^description:\s*(.+)$", re.MULTILINE)
_TAGS_RE = re.compile(r"^tags:\s*\[(.+)\]$", re.MULTILINE)
_TRELLO_BOARD_RE = re.compile(r"^trello_board_id:\s*(.+)$", re.MULTILINE)


class RepoRegistry:
    def __init__(self, entries: list[RepoEntry]) -> None:
        self._entries = entries
        self._by_name = {e.name: e for e in entries}

    @classmethod
    def from_file(cls, path: Path) -> "RepoRegistry":
        text = path.read_text(encoding="utf-8")
        entries = [e for block in _split_blocks(text) if (e := _parse_block(block)) is not None]
        log.info("RepoRegistry loaded %d repos from %s", len(entries), path)
        return cls(entries)

    def all(self) -> list[RepoEntry]:
        return list(self._entries)

    def get(self, name: str) -> RepoEntry | None:
        return self._by_name.get(name)

    def __len__(self) -> int:
        return len(self._entries)


def _split_blocks(text: str) -> list[str]:
    parts = re.split(r"\n##\s+", text)
    return [p.strip() for p in parts if p.strip() and not p.strip().startswith("#")]


def _parse_block(block: str) -> RepoEntry | None:
    lines = block.splitlines()
    name = lines[0].strip()
    if not name:
        return None
    path_m = _PATH_RE.search(block)
    desc_m = _DESC_RE.search(block)
    if not path_m or not desc_m:
        log.warning("Skipping repo block %r — missing path or description", name)
        return None
    tags_m = _TAGS_RE.search(block)
    tags = tuple(t.strip() for t in tags_m.group(1).split(",")) if tags_m else ()
    board_m = _TRELLO_BOARD_RE.search(block)
    trello_board_id = board_m.group(1).strip() if board_m else None
    return RepoEntry(
        name=name,
        path=Path(path_m.group(1).strip()),
        description=desc_m.group(1).strip(),
        tags=tags,
        trello_board_id=trello_board_id,
    )
