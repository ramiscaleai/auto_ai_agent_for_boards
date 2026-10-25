import logging
from pathlib import Path
from types import TracebackType

from ._git import branch_exists, changed_files, current_branch, has_changes, run_git

log = logging.getLogger(__name__)


class MergeConflictError(RuntimeError):
    """Raised when git merge results in conflicts."""


class TaskWorkspace:
    """Manages a per-task git branch inside an existing git repo."""

    def __init__(
        self,
        repo_path: Path,
        task_id: str,
        base_branch: str = "main",
        branch_name: str | None = None,
    ) -> None:
        self.repo_path = repo_path
        self.task_id = task_id
        self.base_branch = base_branch
        self.branch = branch_name or f"task/{task_id}"

    @property
    def cwd(self) -> Path:
        return self.repo_path

    def __enter__(self) -> "TaskWorkspace":
        self._checkout_base()
        self._create_task_branch()
        log.info("TaskWorkspace ready on branch %s", self.branch)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    def stage_and_commit(self, message: str) -> bool:
        """Stage all changes and commit. Returns True if a commit was made."""
        if not has_changes(self.repo_path):
            log.info("No changes to commit")
            return False
        run_git(["add", "-A"], self.repo_path)
        run_git(["commit", "-m", message], self.repo_path)
        log.info("Committed: %s", message)
        return True

    def merge_main_in(self) -> None:
        """Merge base_branch into the current task branch. Raises MergeConflictError on conflicts."""
        result = run_git(["merge", self.base_branch, "--no-edit"], self.repo_path, check=False)
        if result.returncode != 0:
            run_git(["merge", "--abort"], self.repo_path, check=False)
            raise MergeConflictError(f"Merge conflict with {self.base_branch}: {result.stderr.strip()}")
        log.info("Merged %s into %s", self.base_branch, self.branch)

    def merge_back_to_main(self) -> None:
        """Merge task branch into base_branch, then return to task branch."""
        run_git(["checkout", self.base_branch], self.repo_path)
        result = run_git(["merge", self.branch, "--no-edit"], self.repo_path, check=False)
        if result.returncode != 0:
            run_git(["merge", "--abort"], self.repo_path, check=False)
            run_git(["checkout", self.branch], self.repo_path)
            raise MergeConflictError(f"Cannot merge {self.branch} into {self.base_branch}")
        run_git(["checkout", self.branch], self.repo_path)
        log.info("Merged %s back into %s", self.branch, self.base_branch)

    def get_changed_files(self) -> list[Path]:
        return changed_files(self.repo_path, self.base_branch)

    def _checkout_base(self) -> None:
        if current_branch(self.repo_path) != self.base_branch:
            run_git(["checkout", self.base_branch], self.repo_path)

    def _create_task_branch(self) -> None:
        if branch_exists(self.repo_path, self.branch):
            log.warning("Branch %s already exists — reusing", self.branch)
            run_git(["checkout", self.branch], self.repo_path)
        else:
            run_git(["checkout", "-b", self.branch], self.repo_path)
