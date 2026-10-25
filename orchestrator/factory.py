import logging
import os
from pathlib import Path

from ai_agents import AgentRegistry, AgentRunner, CostGuard, make_tracer
from auto_answer import AutoAnswerer, StuckHandler
from boards.repo_backlog_seeder import RepoBacklogSeeder
from boards.trello_board import TrelloBoard
from git_workflow import BranchNamer
from repo_identifier import RepoIdentifier, RepoRegistry

from .config import OrchestratorConfig
from .loop import OrchestratorLoop
from .task_runner import TaskRunner
from .trello_resolver import TrelloBoardResolver

log = logging.getLogger(__name__)


def build_loop(repo_root: Path) -> OrchestratorLoop:
    cfg = OrchestratorConfig.from_env(repo_root)
    board = TrelloBoard(
        api_key=os.environ["TRELLO_API_KEY"],
        token=os.environ["TRELLO_TOKEN"],
        board_id=os.environ["TRELLO_BOARD_ID"],
    )
    registry = AgentRegistry.load(cfg.agents_yml_path, env=dict(os.environ))
    guard = CostGuard(
        per_task_cap_usd=cfg.cost_per_task_usd,
        daily_cap_usd=cfg.cost_per_day_usd,
        state_path=cfg.cost_state_path,
    )
    tracer = make_tracer(dict(os.environ))
    runner = AgentRunner(registry=registry, cost_guard=guard, tracer=tracer)

    repo_registry = RepoRegistry.from_file(cfg.repos_md_path)
    structured_llm = registry.build_structured_llm()
    identifier = RepoIdentifier(repo_registry, structured_llm)
    trello_resolver = TrelloBoardResolver(
        default_api_key=os.environ["TRELLO_API_KEY"],
        default_token=os.environ["TRELLO_TOKEN"],
        default_board_id=os.environ["TRELLO_BOARD_ID"],
        default_to_do_list=cfg.to_do_list,
        default_to_review_list=cfg.to_review_list,
        default_waiting_list=cfg.waiting_list,
        default_backlog_list=cfg.backlog_list,
    )

    branch_namer = BranchNamer(structured_llm)
    backlog_seeder = RepoBacklogSeeder(llm=structured_llm)
    task_runner = TaskRunner(
        board=board, identifier=identifier, runner=runner,
        branch_namer=branch_namer,
        to_review_list=cfg.to_review_list,
        waiting_list=cfg.waiting_list,
        agent_timeout_s=cfg.agent_timeout_min * 60,
        prompt_comment_budget_bytes=cfg.prompt_comment_budget_bytes,
        trello_resolver=trello_resolver,
        backlog_seeder=backlog_seeder,
    )
    stuck_handler = StuckHandler(board=board, waiting_list=cfg.waiting_list)
    auto_answerer = AutoAnswerer(
        board=board,
        waiting_list=cfg.waiting_list,
        to_do_list=cfg.to_do_list,
        auto_answer_hours=cfg.auto_answer_hours,
        llm=structured_llm,
    )
    return OrchestratorLoop(
        board=board,
        task_runner=task_runner,
        to_do_list=cfg.to_do_list,
        poll_interval_s=cfg.poll_interval_s,
        stuck_handler=stuck_handler,
        auto_answerer=auto_answerer,
    )
