#!/usr/bin/env python3
"""Entry point: start the AI board agent loop.

Usage:
  python main.py             # continuous loop (run_forever)
  python main.py --run-once  # single poll iteration then exit (used by systemd)
"""
import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)

log = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto AI Agent for Boards")
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single poll iteration then exit (used by systemd timer)",
    )
    args = parser.parse_args()

    from orchestrator.factory import build_loop
    loop = build_loop(REPO_ROOT)

    if args.run_once:
        log.info("Running single iteration (--run-once)")
        loop.run_once()
    else:
        loop.run_forever()


if __name__ == "__main__":
    main()
