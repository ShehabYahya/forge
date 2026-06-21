from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
import subprocess


class RepositoryInspectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Change:
    status: str
    path: str
    content: bytes


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], check=check,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.decode(errors="replace") if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise RepositoryInspectionError(detail.strip()) from exc


def validate_repo(repo: Path) -> Path:
    resolved = repo.expanduser().resolve(strict=True)
    result = git(resolved, "rev-parse", "--show-toplevel")
    root = Path(result.stdout.decode().strip()).resolve(strict=True)
    if root != resolved:
        raise RepositoryInspectionError("repo_root must be the Git repository root")
    return root


def safe_path(repo: Path, relative: str, *, must_exist: bool = False) -> Path:
    if not relative or "\0" in relative or Path(relative).is_absolute():
        raise RepositoryInspectionError(f"invalid repository-relative path: {relative!r}")
    lexical = Path(os.path.abspath(repo / relative))
    if not lexical.is_relative_to(repo):
        raise RepositoryInspectionError(f"path escapes repository: {relative}")
    if must_exist:
        resolved = lexical.resolve(strict=True)
        if not resolved.is_relative_to(repo):
            raise RepositoryInspectionError(f"path resolves outside repository: {relative}")
    return lexical


def _parse_status(raw: bytes) -> list[tuple[str, str]]:
    fields = raw.split(b"\0")
    changes: list[tuple[str, str]] = []
    index = 0
    while index < len(fields) and fields[index]:
        line = fields[index].decode("utf-8", errors="surrogateescape")
        if line.startswith("1 "):
            parts = line.split(" ", 8)
            changes.append((parts[1], parts[8]))
        elif line.startswith("2 "):
            parts = line.split(" ", 9)
            changes.append((parts[1], parts[9]))
            index += 1  # consume original rename path
        elif line.startswith("? "):
            changes.append(("??", line[2:]))
        elif line.startswith("u "):
            parts = line.split(" ", 10)
            changes.append(("UU", parts[10]))
        index += 1
    return changes


def capture_changes(repo: Path) -> list[Change]:
    repo = validate_repo(repo)
    status = git(repo, "status", "--porcelain=v2", "-z", "--untracked-files=all").stdout
    result: list[Change] = []
    for state, relative in _parse_status(status):
        path = safe_path(repo, relative)
        data = b""
        if path.exists() or path.is_symlink():
            safe_path(repo, relative, must_exist=True)
            if path.is_file():
                try:
                    data = path.read_bytes()
                except OSError as exc:
                    raise RepositoryInspectionError(f"cannot inspect {relative}: {exc}") from exc
        elif "D" in state:
            previous = git(repo, "show", f"HEAD:{relative}", check=False)
            if previous.returncode == 0:
                data = previous.stdout
        result.append(Change(state, relative.replace(os.sep, "/"), data))
    return sorted(result, key=lambda change: (change.path, change.status, change.content))


def digest_changes(changes: list[Change]) -> str:
    digest = hashlib.sha256()
    for change in changes:
        for value in (change.status.encode(), change.path.encode(), change.content):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
    return digest.hexdigest()
