"""E2E: RepoIdentifier picks the right repo using a real LLM."""
import textwrap
from pathlib import Path

import pytest

from ai_agents import AgentRegistry, CostGuard, NoOpTracer
from repo_identifier import RepoIdentifier, RepoRegistry


@pytest.fixture(scope="module")
def registry(tmp_path_factory):
    p = tmp_path_factory.mktemp("repos") / "repos.md"
    p.write_text(textwrap.dedent("""\
        # Repositories

        ## backend
        path: /tmp/backend
        description: Python FastAPI REST API serving user data
        tags: [python, api, fastapi]

        ## frontend
        path: /tmp/frontend
        description: React TypeScript single-page application for end users
        tags: [react, typescript, ui]
    """))
    return RepoRegistry.from_file(p)


@pytest.fixture(scope="module")
def llm(tmp_path_factory):
    yaml_path = Path(__file__).resolve().parents[3] / "config" / "agents.yml"
    reg = AgentRegistry.load(yaml_path, env={})
    return reg.build_structured_llm()


def test_identifies_backend_for_api_task(registry, llm):
    identifier = RepoIdentifier(registry, llm)
    results = identifier.identify("Add a new REST endpoint to list all users")
    names = [r.name for r in results]
    assert "backend" in names, f"Expected backend, got {names}"


def test_identifies_frontend_for_ui_task(registry, llm):
    identifier = RepoIdentifier(registry, llm)
    results = identifier.identify("Fix the login button styling on the homepage")
    names = [r.name for r in results]
    assert "frontend" in names, f"Expected frontend, got {names}"
