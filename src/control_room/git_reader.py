"""Read-only Git adapter for Control Room V0.

Executes a fixed set of read-only `git` subprocess calls against a
configured repository path and classifies the result. This module must
NEVER invoke a Git command capable of mutating repository state (no add,
commit, checkout, switch, reset, clean, stash, fetch, pull, push, merge,
rebase, or tag) and must never perform network access (no fetch).

Every `git` invocation uses an explicit argument array and an explicit
`cwd` -- never a shell string -- so paths containing spaces (a documented
Windows requirement for this module) are handled correctly.

`read_commit_changed_files()` (Mission 7) is the one operation that takes
an argument at all beyond the configured repository path: a commit SHA.
It is restricted to a strict hex-SHA pattern before any subprocess is
spawned, so this module never executes Git against an arbitrary,
caller-supplied revision expression.

`_read_working_tree()` (Mission 8) issues exactly one
`git --no-optional-locks status --porcelain=v2 -z --untracked-files=all
--renames` call and derives both the coarse CLEAN/DIRTY classification
and the full per-path `WorkingTreeChange` detail from that same output --
never a second `git status` invocation, so the two can never disagree
about whether the tree is dirty. `--no-optional-locks` closes off the
one narrow way `git status` can otherwise write to disk (an
opportunistic index stat-cache refresh) as a side effect of what should
be a purely read-only call. `--renames` is passed explicitly so rename
detection does not silently depend on a checkout's local
`status.renames`/`diff.renames` configuration.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from control_room.models import (
    GitStatus,
    TrackingStatus,
    WorkingTreeChange,
    WorkingTreeChangeKind,
    WorkingTreeStatus,
)

logger = logging.getLogger("redline_os.control_room.git_reader")

_DEFAULT_TIMEOUT_SECONDS = 5.0
_HEAD_SHORT_LENGTH = 8

# A commit SHA (full or abbreviated hex) only. Deliberately rejects
# anything else -- including a `-`-prefixed string that `git` might
# otherwise parse as an option -- before a subprocess is ever spawned.
# `read_commit_changed_files()` must never accept an arbitrary revision
# expression (branch name, ref, "HEAD~3", etc.), only a SHA already
# resolved via `commit_exists()`.
_COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")

# A full 40-character hex SHA only -- used to validate each token of
# `git rev-list --parents -n 1`'s own output (never user input). Stricter
# than _COMMIT_SHA_PATTERN above (which also accepts an abbreviated SHA
# for caller-supplied revisions): Git's own `--parents` output always
# prints full SHAs, so a token that doesn't match exactly is a sign the
# output was not what was expected, not a legitimately short reference.
_FULL_COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

# The single-character X/Y porcelain status codes Git's own documentation
# enumerates overall: no change ('.'), Modified, Type-changed, Added,
# Deleted, Renamed, Copied, Unmerged. No single record type actually uses
# all eight, though: Git never emits R/C/U for an ordinary type "1"
# record (a rename/copy is always its own type "2" record; an unmerged
# path is always its own type "u" record), so a per-record-type letter
# set is used instead of this general union -- independent review
# finding: validating every record type against the full union would
# silently accept an impossible ordinary-record status like "U", which
# real Git can never produce for that record type.
_ORDINARY_STATUS_LETTERS = frozenset(".MTAD")
# Type "2" (rename/copy) record: X mirrors the record's own R/C type
# letter (already validated more precisely by the score-field check);
# Y is an ordinary worktree-side letter, never R/C/U.
_RENAME_INDEX_STATUS_LETTERS = frozenset("RC")
_RENAME_WORKTREE_STATUS_LETTERS = frozenset(".MTAD")
# Type "u" (unmerged) record: kept as the general documented union
# rather than narrowed to Git's commonly-seen conflict combinations
# (AA/DD/UU/AU/UA/DU/UD, etc.) -- unlike the ordinary/rename cases above,
# there is no case here of an *impossible* letter to exclude with
# confidence, only a narrower "commonly observed" subset, and this
# module does not guess at Git-version-dependent output shapes it has
# not verified.
_UNMERGED_STATUS_LETTERS = frozenset(".MTADRCU")

# A rename/copy score field is a single R/C type letter followed by one or
# more digits (a similarity percentage, e.g. "R100", "C075") -- never just
# the bare letter, and never trailing non-digit characters. Independent
# Codex review finding: checking only the first character (`score[0] in
# ("R", "C")`) would silently accept a malformed field like "R", "Rabc", or
# "C-1" as a legitimate rename/copy record.
_RENAME_SCORE_PATTERN = re.compile(r"^[RC][0-9]+$")


class _PorcelainParseError(Exception):
    """Internal only: raised by GitReader's own `_parse_porcelain_*`
    helpers on any `git status --porcelain=v2 -z` record shape they do
    not recognize, or a malformed instance of a recognized shape. Always
    caught by `_read_working_tree()` and converted into a
    `(None, message)` result -- never escapes `GitReader`."""


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

        working_tree, working_tree_changes, working_tree_changes_error = self._read_working_tree()
        if working_tree == WorkingTreeStatus.ERROR:
            # The `git status` read itself failed outright (not found,
            # timeout, non-zero exit) -- fail the whole snapshot, exactly
            # as before Mission 8 added working_tree_changes. This is
            # distinct from a malformed-record decode failure below,
            # which leaves branch/HEAD/tracking intact (see GitStatus's
            # working_tree_changes_error docstring).
            return self._error_status(working_tree_changes_error)

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
            working_tree_changes=working_tree_changes,
            working_tree_changes_error=working_tree_changes_error,
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

    def read_commit_changed_files(self, commit: str) -> tuple[list[str] | None, str | None]:
        """Return `(changed_file_paths, error)` -- the repository-relative
        file paths changed by exactly one *non-merge* commit (the
        commit's own diff against its single parent, or against the empty
        tree for a root commit), via a read-only `git diff-tree`. No diff
        content, line counts, author, message, or any other commit
        metadata is read or returned -- file paths only.

        `commit` must already be a resolved commit SHA (see
        `commit_exists()`). Callers must never pass an arbitrary revision
        expression, branch name, or other user-influenced string: this
        method itself refuses (returns an error, spawns no subprocess) any
        value that is not a plain hex commit SHA, which also closes off
        Git interpreting a `-`-prefixed value as an option rather than a
        revision.

        A merge commit (more than one parent) is deliberately *not*
        diffed: `git diff-tree` without an explicit diff strategy for a
        merge can under-report or omit files the merge actually
        introduced, which would silently collapse "merge change-set
        semantics not determined" into "legitimate empty commit" -- a
        correctness bug found by independent review. This method detects
        the parent count first (`git rev-list --parents -n 1`) and
        returns an explicit unavailable result for any commit with more
        than one parent, rather than guessing at first-parent/combined/
        union diff semantics.

        Returns `(paths, None)` on success -- `paths` may legitimately be
        an empty list if a non-merge commit changed no files, which is
        not an error. Returns `(None, <message>)` if the change set could
        not be determined at all: invalid input, a merge commit, Git
        unavailable, timeout, or a non-zero exit. Never raises."""
        if not _COMMIT_SHA_PATTERN.match(commit):
            message = f"refusing to query a non-SHA revision: {commit!r}"
            logger.error("control room git read failed: %s", message)
            return None, message

        parent_count, parent_count_error = self._commit_parent_count(commit)
        if parent_count_error is not None:
            return None, parent_count_error
        if parent_count > 1:
            message = "checkpoint change set unavailable: merge commits are not supported"
            logger.warning("control room git read: %s (commit=%s, parents=%d)", message, commit, parent_count)
            return None, message

        result = self._run(["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", commit])
        if result is None:
            return None, "git command failed while reading checkpoint change set"
        if result.returncode != 0:
            return None, f"git diff-tree failed: {result.stderr.strip()}"

        # NUL-delimited output (`-z`) is parsed on '\0', never split on
        # newlines or whitespace, so a filename containing a space (or,
        # in principle, a newline) cannot be misparsed into two paths.
        paths = [path for path in result.stdout.split("\0") if path]
        return paths, None

    def _commit_parent_count(self, commit: str) -> tuple[int | None, str | None]:
        """Return `(parent_count, error)` for an already-SHA-validated
        commit: 0 for a root commit, 1 for a normal commit, 2+ for a
        merge. Read-only (`git rev-list --parents -n 1 <commit>`).

        A successful (exit 0) result is not trusted at face value: its
        output must be at least one whitespace-separated token, and every
        token must match a full 40-character hex SHA exactly (token 0 the
        commit itself, the rest its parents). Any other shape -- too few
        tokens, a non-hex or short/long token, anything unexpected -- is
        treated as undetermined, never guessed at as a root, normal, or
        merge commit, and the caller never reaches `diff-tree` for it."""
        result = self._run(["rev-list", "--parents", "-n", "1", commit])
        if result is None:
            return None, "git command failed while reading checkpoint parent count"
        if result.returncode != 0:
            return None, f"git rev-list failed while reading checkpoint parent count: {result.stderr.strip()}"

        parts = result.stdout.split()
        if not parts or not all(_FULL_COMMIT_SHA_PATTERN.match(token) for token in parts):
            message = f"unexpected git rev-list output while reading checkpoint parent count: {result.stdout!r}"
            logger.error("control room git read failed: %s", message)
            return None, message

        return len(parts) - 1, None

    # -- internals ------------------------------------------------------

    def _read_working_tree(self) -> tuple[WorkingTreeStatus, list[WorkingTreeChange] | None, str | None]:
        """One `git --no-optional-locks status --porcelain=v2 -z
        --untracked-files=all --renames` call (Mission 8), never a
        second `git status` invocation. `--no-optional-locks` (a
        top-level Git option, hence placed before the subcommand) is
        independent-review hardening: without it, `git status` may
        opportunistically take the index's optional lock and write back
        a refreshed on-disk stat cache as a side effect of an otherwise
        read-only status read -- a real, if narrow, filesystem write this
        module's "never mutates repository state" guarantee should not
        leave open. Returns `(status, changes, changes_error)`:

        - `status` (CLEAN/DIRTY/ERROR) is derived from whether the raw
          output is empty -- a coarse signal that needs no per-record
          decoding, so it stays trustworthy even if `changes` below does
          not.
        - `changes` is the full structured decode of that same output,
          or `None` if it could not be decoded.
        - `changes_error` is set whenever `changes` is `None`: either
          because the `git status` subprocess itself failed (in which
          case `status` is also ERROR, and the caller fails the whole
          snapshot exactly as before Mission 8), or because the
          subprocess succeeded but a record inside its output did not
          match any recognized porcelain-v2 shape (in which case
          `status` remains a trustworthy CLEAN/DIRTY and only the detail
          is unavailable). Never a partial/best-effort `changes` list:
          any unrecognized or malformed record invalidates the entire
          decode."""
        result = self._run(
            ["--no-optional-locks", "status", "--porcelain=v2", "-z", "--untracked-files=all", "--renames"]
        )
        if result is None:
            return WorkingTreeStatus.ERROR, None, "git command failed while reading working-tree status"
        if result.returncode != 0:
            return WorkingTreeStatus.ERROR, None, f"git status failed: {result.stderr.strip()}"

        status = WorkingTreeStatus.DIRTY if result.stdout else WorkingTreeStatus.CLEAN

        try:
            changes = self._parse_porcelain_v2(result.stdout)
        except _PorcelainParseError as exc:
            message = f"unable to parse git status output: {exc}"
            logger.error("control room git read failed: %s", message)
            return status, None, message

        return status, changes, None

    def _parse_porcelain_v2(self, raw: str) -> list[WorkingTreeChange]:
        """Parse the NUL-delimited (`-z`) output of `git status
        --porcelain=v2 --untracked-files=all --renames` into one
        `WorkingTreeChange` per record. Recognizes exactly the five
        record shapes Git documents for this output (ordinary `1`,
        rename/copy `2`, unmerged `u`, untracked `?`, ignored `!`).
        `!` can never legitimately appear here since `--ignored` is
        never passed to this fixed command -- its presence, like any
        other unrecognized token or malformed instance of a recognized
        shape, raises `_PorcelainParseError` rather than being silently
        skipped or best-effort parsed, per the malformed-output lesson
        already applied to `read_commit_changed_files()` (Mission 7):
        successful subprocess execution does not imply trustworthy
        output. A "malformed instance of a recognized shape" includes an
        empty path or original_path (independent review finding: Git
        itself never emits an empty path, so a value this parser cannot
        otherwise validate is a stronger sign of unexpected output than
        a legitimate empty string) and a rename/copy score field that is
        not exactly one `R`/`C` letter followed by one or more digits
        (independent review finding: checking only the first character
        would silently accept "R", "Rabc", or "C-1")."""
        tokens = raw.split("\0")
        # `-z` NUL-terminates every record (including the last), so the
        # final split token is always an empty trailing string for any
        # non-empty output, and the entire split is a single empty
        # string for a clean tree -- neither is itself a record.
        if tokens and tokens[-1] == "":
            tokens = tokens[:-1]

        changes: list[WorkingTreeChange] = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.startswith("1 "):
                changes.append(self._parse_ordinary_record(token))
                index += 1
            elif token.startswith("2 "):
                if index + 1 >= len(tokens):
                    raise _PorcelainParseError(f"rename/copy record missing original path: {token!r}")
                changes.append(self._parse_rename_record(token, tokens[index + 1]))
                index += 2
            elif token.startswith("u "):
                changes.append(self._parse_unmerged_record(token))
                index += 1
            elif token.startswith("? "):
                path = token[2:]
                if not path:
                    raise _PorcelainParseError(f"untracked record has an empty path: {token!r}")
                changes.append(WorkingTreeChange(path=path, kind=WorkingTreeChangeKind.UNTRACKED))
                index += 1
            else:
                raise _PorcelainParseError(f"unrecognized git status record: {token!r}")
        return changes

    def _parse_ordinary_record(self, token: str) -> WorkingTreeChange:
        # "1 XY sub mH mI mW hH hI path" -- 9 space-separated fields,
        # `path` last (and may itself contain spaces, hence maxsplit).
        fields = token.split(" ", 8)
        if len(fields) != 9:
            raise _PorcelainParseError(f"malformed ordinary status record: {token!r}")
        index_status, worktree_status = self._parse_xy(
            fields[1], token, _ORDINARY_STATUS_LETTERS, _ORDINARY_STATUS_LETTERS
        )
        path = fields[8]
        if not path:
            raise _PorcelainParseError(f"ordinary status record has an empty path: {token!r}")
        return WorkingTreeChange(
            path=path,
            index_status=index_status,
            worktree_status=worktree_status,
            kind=WorkingTreeChangeKind.TRACKED,
        )

    def _parse_rename_record(self, token: str, original_path: str) -> WorkingTreeChange:
        # "2 XY sub mH mI mW hH hI Xscore path" -- 10 space-separated
        # fields, `path` last; `origPath` is the following NUL-delimited
        # token, consumed separately by the caller.
        fields = token.split(" ", 9)
        if len(fields) != 10:
            raise _PorcelainParseError(f"malformed rename/copy status record: {token!r}")
        index_status, worktree_status = self._parse_xy(
            fields[1], token, _RENAME_INDEX_STATUS_LETTERS, _RENAME_WORKTREE_STATUS_LETTERS
        )
        score_field = fields[8]
        if not _RENAME_SCORE_PATTERN.match(score_field):
            raise _PorcelainParseError(f"malformed rename/copy score field {score_field!r} in record: {token!r}")
        kind = WorkingTreeChangeKind.RENAMED if score_field[0] == "R" else WorkingTreeChangeKind.COPIED
        path = fields[9]
        if not path:
            raise _PorcelainParseError(f"rename/copy status record has an empty path: {token!r}")
        if not original_path:
            raise _PorcelainParseError(f"rename/copy status record has an empty original path: {token!r}")
        return WorkingTreeChange(
            path=path,
            original_path=original_path,
            index_status=index_status,
            worktree_status=worktree_status,
            kind=kind,
        )

    def _parse_unmerged_record(self, token: str) -> WorkingTreeChange:
        # "u XY sub m1 m2 m3 mW h1 h2 h3 path" -- 11 space-separated
        # fields, `path` last.
        fields = token.split(" ", 10)
        if len(fields) != 11:
            raise _PorcelainParseError(f"malformed unmerged status record: {token!r}")
        index_status, worktree_status = self._parse_xy(
            fields[1], token, _UNMERGED_STATUS_LETTERS, _UNMERGED_STATUS_LETTERS
        )
        path = fields[10]
        if not path:
            raise _PorcelainParseError(f"unmerged status record has an empty path: {token!r}")
        return WorkingTreeChange(
            path=path,
            index_status=index_status,
            worktree_status=worktree_status,
            kind=WorkingTreeChangeKind.CONFLICTED,
        )

    @staticmethod
    def _parse_xy(
        xy: str, token: str, index_letters: frozenset[str], worktree_letters: frozenset[str]
    ) -> tuple[str | None, str | None]:
        if len(xy) != 2 or xy[0] not in index_letters or xy[1] not in worktree_letters:
            raise _PorcelainParseError(f"malformed status code {xy!r} in record: {token!r}")
        index_status = None if xy[0] == "." else xy[0]
        worktree_status = None if xy[1] == "." else xy[1]
        return index_status, worktree_status

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
