import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch


def _load_module() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "scripts" / "trello" / "trello_cli.py"
    spec = importlib.util.spec_from_file_location("trello_cli_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    fake_dotenv = ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda *_args, **_kwargs: None
    with patch.dict("sys.modules", {"dotenv": fake_dotenv}):
        spec.loader.exec_module(module)
    return module


def test_seed_current_repo_backlog_dry_run_uses_backlog_env(capsys):
    module = _load_module()
    board = MagicMock()
    args = MagicMock(list=None, dry_run=True)

    with patch.dict(module.os.environ, {"TRELLO_BACKLOG_LIST_NAME": "Backlog"}, clear=False):
        with patch.object(module, "_make_board", return_value=(board, "To Do")):
            rc = module._cmd_seed_current_repo_backlog(args)

    out = capsys.readouterr().out
    assert rc == 0
    assert "dry_run=True" in out
    assert "list='Backlog'" in out


def test_build_parser_supports_seed_current_repo_backlog():
    module = _load_module()

    parser = module._build_parser()
    args = parser.parse_args(["seed-current-repo-backlog", "--dry-run"])

    assert args.command == "seed-current-repo-backlog"
    assert args.dry_run is True


def test_add_task_passes_description_to_board(capsys):
    module = _load_module()
    board = MagicMock()
    board.create_task.return_value = SimpleNamespace(
        id="card1",
        name="Ship feature",
        description="Detailed implementation notes",
        list_name="Doing",
        url="https://trello.com/c/card1",
    )
    args = module._build_parser().parse_args(
        [
            "add-task",
            "--name",
            "Ship feature",
            "--description",
            "Detailed implementation notes",
            "--list",
            "Doing",
        ]
    )

    with patch.object(module, "_make_board", return_value=(board, "To Do")):
        rc = module._cmd_add_task(args)

    assert rc == 0
    assert "Created card: https://trello.com/c/card1" in capsys.readouterr().out
    board.create_task.assert_called_once_with(
        "Doing", "Ship feature", "Detailed implementation notes"
    )


def test_add_task_description_defaults_to_empty_string():
    module = _load_module()

    args = module._build_parser().parse_args(["add-task", "--name", "Ship feature"])

    assert args.description == ""
