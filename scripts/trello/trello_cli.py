"""Thin operator-facing CLI over boards.TrelloBoard."""
import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from boards.backlog import current_repo_backlog, seed_backlog  # noqa: E402
from boards.trello_board import TrelloAPIError, TrelloBoard, list_boards_for_token  # noqa: E402

_log = logging.getLogger("trello_cli")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Required env var {name} not set in .env")
    return value


def _make_board() -> tuple[TrelloBoard, str]:
    board = TrelloBoard(
        api_key=_require_env("TRELLO_API_KEY"),
        token=_require_env("TRELLO_TOKEN"),
        board_id=_require_env("TRELLO_BOARD_ID"),
    )
    return board, _require_env("TRELLO_TO_DO_LIST_NAME")


def _cmd_add_task(args: argparse.Namespace) -> int:
    board, to_do_list = _make_board()
    target_list = args.list or to_do_list
    task = board.create_task(target_list, args.name, getattr(args, "description", ""))
    print(f"Created card: {task.url}")
    if args.comment:
        board.add_comment(task.id, args.comment)
        print(f"Added comment: {args.comment!r}")
    return 0


def _cmd_list_tasks(args: argparse.Namespace) -> int:
    board, to_do_list = _make_board()
    target_list = args.list or to_do_list
    tasks = board.list_tasks(target_list)
    if not tasks:
        print(f"(no tasks in list {target_list!r})")
        return 0
    for task in tasks:
        print(f"{task.id}  {task.name}")
    return 0


def _cmd_list_boards(_args: argparse.Namespace) -> int:
    boards = list_boards_for_token(_require_env("TRELLO_API_KEY"), _require_env("TRELLO_TOKEN"))
    for board in boards:
        print(f"{board['id']}  {board['name']}")
    return 0


def _cmd_seed_current_repo_backlog(args: argparse.Namespace) -> int:
    board, _to_do_list = _make_board()
    target_list = args.list or os.environ.get("TRELLO_BACKLOG_LIST_NAME", "Backlog")
    result = seed_backlog(board, target_list, current_repo_backlog(), dry_run=args.dry_run)
    mode = "Would create" if args.dry_run else "Created"
    for name in result.created:
        print(f"{mode}: {name}")
    for name in result.skipped:
        print(f"Skipped existing: {name}")
    print(
        f"Summary: created={len(result.created)} skipped={len(result.skipped)} "
        f"list={target_list!r} dry_run={args.dry_run}"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trello-cli", description="Operator CLI for the Trello board adapter.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add-task", help="Create a card and optionally comment on it.")
    p_add.add_argument("--name", required=True, help="Card title.")
    p_add.add_argument("--description", default="", help="Card description (default: empty).")
    p_add.add_argument("--comment", help="Comment to add after creation.")
    p_add.add_argument("--list", help="Override target list name (default: $TRELLO_TO_DO_LIST_NAME).")
    p_add.set_defaults(func=_cmd_add_task)

    p_ls = sub.add_parser("list-tasks", help="Print tasks in a list.")
    p_ls.add_argument("--list", help="List name (default: $TRELLO_TO_DO_LIST_NAME).")
    p_ls.set_defaults(func=_cmd_list_tasks)

    p_lb = sub.add_parser("list-boards", help="Print boards visible to your token.")
    p_lb.set_defaults(func=_cmd_list_boards)

    p_seed = sub.add_parser(
        "seed-current-repo-backlog",
        help="Create the curated top-30 backlog for this repo in the Backlog list.",
    )
    p_seed.add_argument("--list", help="Target list name (default: $TRELLO_BACKLOG_LIST_NAME or 'Backlog').")
    p_seed.add_argument("--dry-run", action="store_true", help="Print what would be created without creating cards.")
    p_seed.set_defaults(func=_cmd_seed_current_repo_backlog)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    load_dotenv(REPO_ROOT / ".env")
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (TrelloAPIError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
