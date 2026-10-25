import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OrchestratorConfig:
    to_do_list: str
    to_review_list: str
    waiting_list: str
    backlog_list: str
    repos_md_path: Path
    poll_interval_s: int
    auto_answer_hours: int
    cost_per_task_usd: float
    cost_per_day_usd: float
    cost_state_path: Path
    agents_yml_path: Path
    agent_timeout_min: int
    prompt_comment_budget_bytes: int

    @classmethod
    def from_env(cls, repo_root: Path) -> "OrchestratorConfig":
        return cls(
            to_do_list=os.environ.get("TRELLO_TO_DO_LIST_NAME", "To Do"),
            to_review_list=os.environ.get("TRELLO_TO_REVIEW_LIST_NAME", "To Review"),
            waiting_list=os.environ.get("TRELLO_WAITING_LIST_NAME", "Waiting for answers"),
            backlog_list=os.environ.get("TRELLO_BACKLOG_LIST_NAME", "Backlog"),
            repos_md_path=Path(os.environ.get("REPOS_MD_PATH", str(repo_root / "repos.md"))),
            poll_interval_s=int(os.environ.get("POLL_INTERVAL_S", "60")),
            auto_answer_hours=int(os.environ.get("AUTO_ANSWER_HOURS", "48")),
            cost_per_task_usd=float(os.environ.get("COST_PER_TASK_USD", "0.50")),
            cost_per_day_usd=float(os.environ.get("COST_PER_DAY_USD", "5.00")),
            cost_state_path=Path(
                os.environ.get("COST_STATE_PATH", str(Path.home() / ".cache" / "auto_ai_agent" / "spend.json"))
            ),
            agents_yml_path=repo_root / "config" / "agents.yml",
            agent_timeout_min=int(os.environ.get("AGENT_TIMEOUT_MIN", "30")),
            prompt_comment_budget_bytes=int(os.environ.get("PROMPT_COMMENT_BUDGET_BYTES", "16000")),
        )
