import sys
from unittest.mock import MagicMock, patch

import main


def test_main_run_once_calls_single_iteration():
    loop = MagicMock()
    with patch.object(sys, "argv", ["main.py", "--run-once"]):
        with patch("orchestrator.factory.build_loop", return_value=loop) as build_loop:
            main.main()

    build_loop.assert_called_once_with(main.REPO_ROOT)
    loop.run_once.assert_called_once_with()
    loop.run_forever.assert_not_called()


def test_main_default_runs_forever():
    loop = MagicMock()
    with patch.object(sys, "argv", ["main.py"]):
        with patch("orchestrator.factory.build_loop", return_value=loop) as build_loop:
            main.main()

    build_loop.assert_called_once_with(main.REPO_ROOT)
    loop.run_forever.assert_called_once_with()
    loop.run_once.assert_not_called()
