import os
import re
from dataclasses import dataclass
from datetime import timezone

from ai_agents import redact_secrets
from boards.board import Comment, Task
from repo_identifier.models import RepoEntry

_STATUS_ONLY_PATTERNS = (
    re.compile(r"(?im)^started work\b"),
    re.compile(r"(?im)^working on this task\b"),
    re.compile(r"(?im)^moved (?:card|task)\b"),
    re.compile(r"(?im)^task .* moved to\b"),
    re.compile(r"(?im)^cost guard\b"),
)
_BOT_AUTHOR_RE = re.compile(r"\b(ai agent|auto[- ]?answer|bot|orchestrator)\b", re.IGNORECASE)

_INSTRUCTIONS = """\
Instructions:
- Implement the task completely in the current directory
- Write clean, working, secure code with no unused imports or dead code
- Stage and commit your changes using: git add -A && git commit -m "<message>"
- If you get stuck or need clarification, end your response with:
  QUESTIONS:
  1. <first question>
  2. <second question>
"""


@dataclass(frozen=True)
class RepoContext:
    repos: tuple[RepoEntry, ...]
    rationale: str
    current_branch: str


def build_prompt(
    task: Task,
    *,
    comments: list[Comment] | None = None,
    repo_context: RepoContext | None = None,
    comment_budget_bytes: int = 16_000,
) -> str:
    sections = [
        "You are an AI software engineer implementing a task from the project board.",
        "",
        f"Task: {task.name}",
        f"URL: {task.url}",
    ]

    optional_sections = [
        _simple_section("List", task.list_name),
        _simple_section("Labels", ", ".join(task.labels)),
        _simple_section("Due", _format_due(task)),
        _multiline_section("Description", task.description.strip() if task.description else "(no description provided)"),
        _multiline_section("Checklist", _format_checklist(task)),
        _multiline_section("Attachments", _format_attachments(task)),
        _multiline_section("Discussion", _format_discussion(comments or [], comment_budget_bytes)),
        _multiline_section("Repo context", _format_repo_context(repo_context)),
    ]
    sections.extend(section for section in optional_sections if section)
    sections.extend(["", _INSTRUCTIONS.rstrip()])
    return "\n".join(sections) + "\n"


def _simple_section(label: str, value: str) -> str:
    if not value:
        return ""
    return f"{label}: {value}"


def _multiline_section(label: str, body: str) -> str:
    if not body:
        return ""
    return f"\n{label}:\n{body}"


def _format_due(task: Task) -> str:
    if task.due_at is None:
        return ""
    due_at = task.due_at
    if due_at.tzinfo is None:
        return due_at.date().isoformat()
    return due_at.astimezone(timezone.utc).date().isoformat()


def _format_checklist(task: Task) -> str:
    if not task.checklist_items:
        return ""
    return "\n".join(f"[{'x' if item.checked else ' '}] {item.name}" for item in task.checklist_items)


def _format_attachments(task: Task) -> str:
    if not task.attachments:
        return ""
    lines = []
    for attachment in task.attachments:
        if attachment.name and attachment.name != attachment.url:
            lines.append(f"- {attachment.name}: {attachment.url}")
        else:
            lines.append(f"- {attachment.url}")
    return "\n".join(lines)


def _format_discussion(comments: list[Comment], budget_bytes: int) -> str:
    rendered = [_render_comment(comment) for comment in comments if not _is_status_only(comment)]
    if not rendered:
        return ""
    return _truncate_comment_block(rendered, budget_bytes)


def _render_comment(comment: Comment) -> str:
    redacted = redact_secrets(comment.text, os.environ)
    created_at = comment.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    stamp = created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    bot_label = " [BOT]" if _is_bot_comment(comment) else ""
    body = "\n".join(f"> {line}" for line in redacted.splitlines()) or "> "
    return f"[{stamp}] <{comment.author}>{bot_label}:\n{body}"


def _is_bot_comment(comment: Comment) -> bool:
    text = comment.text.strip()
    return bool(
        _BOT_AUTHOR_RE.search(comment.author)
        or text.startswith("[AI Agent]")
        or text.startswith("QUESTIONS:")
    )


def _is_status_only(comment: Comment) -> bool:
    text = comment.text.strip()
    return any(pattern.search(text) for pattern in _STATUS_ONLY_PATTERNS)


def _truncate_comment_block(rendered_comments: list[str], budget_bytes: int) -> str:
    if budget_bytes <= 0:
        return ""

    def total_size(parts: list[str]) -> int:
        return len("\n\n".join(parts).encode("utf-8"))

    if total_size(rendered_comments) <= budget_bytes:
        return "\n\n".join(rendered_comments)

    chosen: list[str] = []
    for omitted in range(1, len(rendered_comments) + 1):
        kept = rendered_comments[omitted:]
        if not kept:
            marker = f"[... {len(rendered_comments)} earlier comments omitted ...]"
            return marker if len(marker.encode("utf-8")) <= budget_bytes else ""
        marker = f"[... {omitted} earlier comments omitted ...]"
        candidate = [marker, *kept]
        if total_size(candidate) <= budget_bytes:
            chosen = candidate
            break

    if chosen:
        return "\n\n".join(chosen)

    latest = rendered_comments[-1]
    if len(latest.encode("utf-8")) <= budget_bytes:
        return latest
    return _truncate_bytes(latest, budget_bytes)


def _truncate_bytes(text: str, budget_bytes: int) -> str:
    if budget_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")[:budget_bytes]
    while True:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]


def _format_repo_context(repo_context: RepoContext | None) -> str:
    if repo_context is None:
        return ""
    lines = []
    if repo_context.repos:
        repo_lines = [f"- {repo.name}: {repo.path}" for repo in repo_context.repos]
        lines.append("Target repo(s):")
        lines.extend(repo_lines)
    if repo_context.rationale:
        lines.append(f"Routing rationale: {repo_context.rationale}")
    if repo_context.current_branch:
        lines.append(f"Current branch: {repo_context.current_branch}")
    return "\n".join(lines)
