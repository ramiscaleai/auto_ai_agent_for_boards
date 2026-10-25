import os
from pathlib import Path
from unittest.mock import patch

from orchestrator.config import OrchestratorConfig

ROOT = Path("/repo")


def _cfg(**overrides):
    env = {
        "TRELLO_TO_DO_LIST_NAME": "To Do",
        "TRELLO_TO_REVIEW_LIST_NAME": "To Review",
        "TRELLO_WAITING_LIST_NAME": "Waiting for answers",
        "POLL_INTERVAL_S": "30",
        "AUTO_ANSWER_HOURS": "24",
        "COST_PER_TASK_USD": "0.25",
        "COST_PER_DAY_USD": "2.00",
        **overrides,
    }
    with patch.dict(os.environ, env, clear=False):
        return OrchestratorConfig.from_env(ROOT)


def test_defaults():
    cfg = _cfg()
    assert cfg.to_do_list == "To Do"
    assert cfg.to_review_list == "To Review"
    assert cfg.poll_interval_s == 30
    assert cfg.auto_answer_hours == 24


def test_cost_floats():
    cfg = _cfg()
    assert cfg.cost_per_task_usd == 0.25
    assert cfg.cost_per_day_usd == 2.00


def test_agents_yml_path():
    cfg = _cfg()
    assert cfg.agents_yml_path == ROOT / "config" / "agents.yml"


def test_repos_md_path_default():
    cfg = _cfg()
    assert cfg.repos_md_path == ROOT / "repos.md"


def test_repos_md_path_override():
    cfg = _cfg(REPOS_MD_PATH="/custom/repos.md")
    assert cfg.repos_md_path == Path("/custom/repos.md")


def test_agent_timeout_min_default():
    cfg = _cfg()
    assert cfg.agent_timeout_min == 30


def test_agent_timeout_min_override():
    cfg = _cfg(AGENT_TIMEOUT_MIN="60")
    assert cfg.agent_timeout_min == 60


def test_prompt_comment_budget_default():
    cfg = _cfg()
    assert cfg.prompt_comment_budget_bytes == 16000


def test_prompt_comment_budget_override():
    cfg = _cfg(PROMPT_COMMENT_BUDGET_BYTES="4096")
    assert cfg.prompt_comment_budget_bytes == 4096
