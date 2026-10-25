import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    log.debug("git %s (cwd=%s)", " ".join(args), cwd)
    result = subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        log.error("git %s failed: %s", " ".join(args), result.stderr.strip())
        if check:
            result.check_returncode()
    return result


def current_branch(cwd: Path) -> str:
    return run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()


def branch_exists(cwd: Path, name: str) -> bool:
    r = run_git(["branch", "--list", name], cwd, check=False)
    return bool(r.stdout.strip())


def has_changes(cwd: Path) -> bool:
    r = run_git(["status", "--porcelain"], cwd)
    return bool(r.stdout.strip())


def changed_files(cwd: Path, base: str) -> list[Path]:
    r = run_git(["diff", "--name-only", f"{base}...HEAD"], cwd, check=False)
    lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    return [Path(l) for l in lines]
