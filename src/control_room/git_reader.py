"""Read-only Git adapter for Control Room V0.

Executes a fixed set of read-only `git` subprocess calls against a
configured repository path and classifies the result. This module must
NEVER invoke a Git command capable of mutating repository state (no add,
commit, checkout, switch, reset, clean, stash, fetch, pull, push, merge,
rebase, or tag) and must never perform network access (no fetch).

Every `git` invocation uses an explicit argument array and an explicit
`cwd` -- never a shell string -- so paths containing spaces (a documented
Windows requirement for this module) are handled correctly.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from control_room.models import GitStatus, TrackingStatus, WorkingTreeStatus

logger = logging.getLogger("redline_os.control_room.git_reader")

_DEFAULT_TIMEOUT_SECONDS = 5.0
_HEAD_SHORT_LENGTH = 8


class GitReader:
    """Reads live, read-only Git state for a single repository path."""

    def __init__(self, repository_path: str | Path, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS):
        self._repository_path = Path(repository_path)
        self._timeout_seconds = timeout_seconds

    def read_status(self) -> GitStatus:
        """Return the current GitStatus for this repository. Never raises --
        any failure is captured as an ERROR/NOT_A_REPOSITORY classification
        with a diagnostic in `error`, and logged."""
        if not self._repository_path.is_dir():
            message = f"repository path does not exist or is not a directory: {self._repository_path}"
            logger.error("control room git read failed: %s", message)
            return GitStatus(
                repository_valid=False,
                working_tree=WorkingTreeStatus.NOT_A_REPOSITORY,
                tracking=TrackingStatus.NOT_A_REPOSITORY,
                error=message,
            )

        is_repo_result = self._run(["rev-parse", "--is-inside-work-tree"])
        if is_repo_result is None:
            return self._error_status("git command failed while checking repository validity")
        if is_repo_result.returncode != 0 or is_repo_result.stdout.strip() != "true":
            message = f"not a Git repository: {self._repository_path}"
            logger.warning("control room git read: %s", message)
            return GitStatus(
                repository_valid=False,
                working_tree=WorkingTreeStatus.NOT_A_REPOSITORY,
                tracking=TrackingStatus.NOT_A_REPOSITORY,
                error=message,
            )

        head_result = self._run(["rev-parse", "HEAD"])
        if head_result is None:
            return self._error_status("git command failed while reading HEAD")
        if head_result.returncode != 0:
            return self._error_status(f"unable to resolve HEAD (no commits yet?): {head_result.stderr.strip()}")
        head_sha = head_result.stdout.strip()

        branch_result = self._run(["branch", "--show-current"])
        if branch_result is None or branch_result.returncode != 0:
            return self._error_status("git command failed while reading current branch")
        branch = branch_result.stdout.strip() or None
        detached_head = branch is None

        working_tree, error = self._read_working_tree()
        if error:
            return self._error_status(error)

        tracking, upstream, ahead, behind, tracking_error = self._read_tracking(detached_head)
        if tracking_error:
            return self._error_status(tracking_error)

        return GitStatus(
            repository_valid=True,
            branch=branch,
            detached_head=detached_head,
            head_sha=head_sha,
            head_sha_short=head_sha[:_HEAD_SHORT_LENGTH],
            working_tree=working_tree,
            tracking=tracking,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
        )

    def commit_exists(self, commit: str) -> bool | None:
        """Return True/False if `commit` can (not) be resolved as a commit
        object in this repository, or None if that could not be determined
        (Git unavailable, timeout, or the repository itself is invalid)."""
        result = self._run(["cat-file", "-e", f"{commit}^{{commit}}"])
        if result is None:
            return None
        return result.returncode == 0

    # -- internals ------------------------------------------------------

    def _read_working_tree(self) -> tuple[WorkingTreeStatus, str | None]:
        status_result = self._run(["status", "--porcelain"])
        if status_result is None:
            return WorkingTreeStatus.ERROR, "git command failed while reading working-tree status"
        if status_result.returncode != 0:
            return WorkingTreeStatus.ERROR, f"git status failed: {status_result.stderr.strip()}"
        if status_result.stdout.strip():
            return WorkingTreeStatus.DIRTY, None
        return WorkingTreeStatus.CLEAN, None

    def _read_tracking(
        self, detached_head: bool
    ) -> tuple[TrackingStatus, str | None, int | None, int | None, str | None]:
        if detached_head:
            return TrackingStatus.DETACHED_HEAD, None, None, None, None

        upstream_result = self._run(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
        if upstream_result is None:
            return TrackingStatus.ERROR, None, None, None, "git command failed while reading upstream branch"
        if upstream_result.returncode != 0:
            # No upstream configured is an expected, non-error condition.
            return TrackingStatus.NO_UPSTREAM, None, None, None, None
        upstream = upstream_result.stdout.strip()

        count_result = self._run(["rev-list", "--left-right", "--count", "HEAD...@{u}"])
        if count_result is None:
            return TrackingStatus.ERROR, upstream, None, None, "git command failed while reading ahead/behind counts"
        if count_result.returncode != 0:
            return TrackingStatus.ERROR, upstream, None, None, f"git rev-list failed: {count_result.stderr.strip()}"

        parts = count_result.stdout.split()
        if len(parts) != 2:
            return TrackingStatus.ERROR, upstream, None, None, f"unexpected rev-list output: {count_result.stdout!r}"
        ahead, behind = int(parts[0]), int(parts[1])

        if ahead == 0 and behind == 0:
            tracking = TrackingStatus.SYNCHRONIZED
        elif ahead > 0 and behind == 0:
            tracking = TrackingStatus.AHEAD
        elif ahead == 0 and behind > 0:
            tracking = TrackingStatus.BEHIND
        else:
            tracking = TrackingStatus.DIVERGED
        return tracking, upstream, ahead, behind, None

    def _run(self, args: list[str]) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self._repository_path,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError:
            logger.error("control room git read failed: git executable not found on PATH")
            return None
        except subprocess.TimeoutExpired:
            logger.error("control room git read failed: git command timed out (%s)", args)
            return None
        except OSError as exc:
            logger.error("control room git read failed: %s", exc)
            return None

    def _error_status(self, message: str) -> GitStatus:
        logger.error("control room git read failed: %s", message)
        return GitStatus(
            repository_valid=False,
            working_tree=WorkingTreeStatus.ERROR,
            tracking=TrackingStatus.ERROR,
            error=message,
        )
