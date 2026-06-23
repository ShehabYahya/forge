from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .diff import Change, RepositoryInspectionError, safe_path, validate_repo

_TMP_PREFIX = "forge-baseline-"


def _capture_env(tmp_index: str) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = tmp_index
    return env


def _git_with_index(repo: Path, tmp_index: str, *args: str,
                    check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=_capture_env(tmp_index),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc, subprocess.CalledProcessError)
            else str(exc)
        )
        raise RepositoryInspectionError(detail.strip()) from exc


def capture_tree(repo: Path) -> str:
    """Capture the full worktree state as a Git tree object.

    Uses ``GIT_INDEX_FILE`` on a temporary index so the user's real
    ``.git/index`` is never touched.  Prefers ``read-tree HEAD`` when a
    HEAD commit exists; falls back to an empty index otherwise.
    """
    repo = validate_repo(repo)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=_TMP_PREFIX)
    os.close(tmp_fd)
    try:
        # Populate the temporary index from HEAD when possible.
        try:
            _git_with_index(repo, tmp_path, "read-tree", "HEAD")
        except RepositoryInspectionError:
            # Repo with no commits: remove the empty temp file so
            # git add -A creates a fresh valid index from scratch.
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
        _git_with_index(repo, tmp_path, "add", "-A", "--", ".")
        result = _git_with_index(repo, tmp_path, "write-tree")
        tree_sha = result.stdout.decode("ascii").strip()
        if not tree_sha or len(tree_sha) != 40:
            raise RepositoryInspectionError(
                f"git write-tree returned unexpected output: {tree_sha!r}"
            )
        return tree_sha
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def _parse_diff_name_status(raw: bytes) -> list[tuple[str, str]]:
    """Parse ``git diff --name-status -z`` output (no ``-M``).

    Format: ``<status>\\0<path>\\0`` per entry.
    Status codes: ``A``, ``D``, ``M``, ``T``.
    """
    fields = raw.split(b"\0")
    changes: list[tuple[str, str]] = []
    idx = 0
    while idx < len(fields) - 1:
        if not fields[idx]:
            idx += 1
            continue
        status = fields[idx].decode("ascii", errors="replace").strip()
        idx += 1
        path = fields[idx].decode("utf-8", errors="surrogateescape")
        idx += 1
        if status and path:
            changes.append((status, path))
    return changes


def diff_trees(repo: Path, from_tree: str, to_tree: str) -> list[Change]:
    """Return changes between two tree SHAs.

    Rename detection is intentionally disabled (no ``-M``); a rename
    appears as a delete + add pair.
    """
    repo = validate_repo(repo)
    raw = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-status", "--no-renames", "-z",
         from_tree, to_tree],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False,
    ).stdout
    result: list[Change] = []
    for status, relative in _parse_diff_name_status(raw):
        path = safe_path(repo, relative)
        data = b""
        if path.exists() or path.is_symlink():
            safe_path(repo, relative, must_exist=True)
            if path.is_file():
                try:
                    data = path.read_bytes()
                except OSError as exc:
                    raise RepositoryInspectionError(
                        f"cannot inspect {relative}: {exc}"
                    ) from exc
        elif status == "D":
            # Deleted file: retrieve content from the source tree.
            prev = subprocess.run(
                ["git", "-C", str(repo), "cat-file", "blob",
                 f"{from_tree}:{relative}"],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                shell=False,
            )
            if prev.returncode == 0:
                data = prev.stdout
        result.append(Change(status, relative.replace(os.sep, "/"), data))
    return sorted(result, key=lambda change: (change.path, change.status,
                                               change.content))


def sweep_temp_dir(runtime_root: Path | None = None) -> None:
    """Remove stale temporary index files left over from prior crashes."""
    target = runtime_root or Path.home() / ".forge" / "tmp"
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    for entry in target.iterdir():
        if entry.name.startswith(_TMP_PREFIX):
            try:
                entry.unlink()
            except OSError:
                pass
