import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from boards.board import Attachment, ChecklistItem, Comment, Task
from orchestrator.prompt import RepoContext, build_prompt
from repo_identifier.models import RepoEntry


def _task(**kwargs):
    defaults = dict(
        id="t1",
        name="Add login",
        description="OAuth2 flow",
        list_name="To Do",
        url="https://trello.com/c/abc",
        labels=("backend", "urgent"),
        due_at=datetime(2026, 4, 30, 15, 0, tzinfo=timezone.utc),
        checklist_items=(
            ChecklistItem(name="Add endpoint", checked=True),
            ChecklistItem(name="Write tests", checked=False),
        ),
        attachments=(
            Attachment(name="spec.pdf", url="https://files.example/spec.pdf"),
            Attachment(name="", url="https://files.example/mock.png"),
        ),
    )
    return Task(**{**defaults, **kwargs})


def _comment(author: str, text: str, day: int) -> Comment:
    return Comment(
        id=f"c{day}",
        author=author,
        text=text,
        created_at=datetime(2026, 4, day, 10, 0, tzinfo=timezone.utc),
    )


def _repo_context() -> RepoContext:
    return RepoContext(
        repos=(
            RepoEntry(name="backend", path=Path("/repos/backend"), description="API"),
            RepoEntry(name="frontend", path=Path("/repos/frontend"), description="UI"),
        ),
        rationale="Backend owns the API change; frontend is affected by the integration surface.",
        current_branch="task/add-login-t1ab",
    )


def test_contains_core_fields():
    prompt = build_prompt(_task())
    assert "Task: Add login" in prompt
    assert "URL: https://trello.com/c/abc" in prompt
    assert "Description:\nOAuth2 flow" in prompt


def test_empty_description_fallback():
    prompt = build_prompt(_task(description=""))
    assert "(no description provided)" in prompt


def test_contains_questions_hint():
    assert "QUESTIONS" in build_prompt(_task())


def test_prompt_field_order_matches_contract():
    prompt = build_prompt(
        _task(),
        comments=[
            _comment("Alice", "First clarification", 20),
            _comment("AI Agent", "[AI Agent] Auto-answer after 48h:\nUse PostgreSQL.", 21),
        ],
        repo_context=_repo_context(),
    )

    ordered_markers = [
        "Task: Add login",
        "URL: https://trello.com/c/abc",
        "List: To Do",
        "Labels: backend, urgent",
        "Due: 2026-04-30",
        "Description:\nOAuth2 flow",
        "Checklist:\n[x] Add endpoint\n[ ] Write tests",
        "Attachments:\n- spec.pdf: https://files.example/spec.pdf\n- https://files.example/mock.png",
        "Discussion:\n[2026-04-20T10:00:00Z] <Alice>:",
        "Repo context:\nTarget repo(s):\n- backend: /repos/backend\n- frontend: /repos/frontend",
        "Instructions:",
    ]

    positions = [prompt.index(marker) for marker in ordered_markers]
    assert positions == sorted(positions)


def test_discussion_formats_comments_oldest_first_and_marks_bots():
    prompt = build_prompt(
        _task(),
        comments=[
            _comment("Alice", "Line 1\nLine 2", 20),
            _comment("AI Agent", "[AI Agent] Questions about this task:\n\n1. What DB?", 21),
        ],
    )

    assert "[2026-04-20T10:00:00Z] <Alice>:" in prompt
    assert "> Line 1\n> Line 2" in prompt
    assert "[2026-04-21T10:00:00Z] <AI Agent> [BOT]:" in prompt
    assert prompt.index("Alice") < prompt.index("AI Agent")


def test_discussion_filters_status_only_comments():
    prompt = build_prompt(
        _task(),
        comments=[
            _comment("Automation", "Started work on this task.", 20),
            _comment("Bob", "Please keep this behind a feature flag.", 21),
        ],
    )

    assert "Started work on this task." not in prompt
    assert "Please keep this behind a feature flag." in prompt


def test_discussion_redacts_secrets():
    env = {"OPENROUTER_API_KEY": "top-secret-value"}
    with patch.dict(os.environ, env, clear=False):
        prompt = build_prompt(
            _task(),
            comments=[_comment("Bob", "Use key top-secret-value for testing only.", 20)],
        )

    assert "top-secret-value" not in prompt
    assert "***" in prompt


def test_discussion_truncation_keeps_most_recent_comments():
    prompt = build_prompt(
        _task(),
        comments=[
            _comment("Alice", "oldest", 20),
            _comment("Bob", "middle", 21),
            _comment("Carol", "newest", 22),
        ],
        comment_budget_bytes=90,
    )

    assert "[... 2 earlier comments omitted ...]" in prompt
    assert "oldest" not in prompt
    assert "middle" not in prompt
    assert "newest" in prompt


def test_discussion_omitted_when_empty():
    prompt = build_prompt(_task(), comments=[])
    assert "\nDiscussion:\n" not in prompt


def test_omits_empty_optional_sections():
    prompt = build_prompt(
        _task(labels=(), due_at=None, checklist_items=(), attachments=()),
        comments=[],
        repo_context=None,
    )

    assert "Labels:" not in prompt
    assert "Due:" not in prompt
    assert "Checklist:" not in prompt
    assert "Attachments:" not in prompt
    assert "Discussion:" not in prompt
    assert "Repo context:" not in prompt
