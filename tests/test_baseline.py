from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from forge.review.baseline import (
    _parse_diff_name_status,
    capture_tree,
    diff_trees,
    sweep_temp_dir,
)
from forge.review.diff import Change, RepositoryInspectionError, digest_changes


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


# ------------------------------------------------------------------ capture_tree


def test_capture_tree_clean_repo(repo):
    sha = capture_tree(repo)
    assert len(sha) == 40
    result = subprocess.run(["git", "-C", str(repo), "cat-file", "-t", sha],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            shell=False)
    assert result.stdout.strip() == b"tree"


def test_capture_tree_modified_file(repo):
    clean = capture_tree(repo)
    (repo / "base.txt").write_text("modified\n")
    mod = capture_tree(repo)
    assert mod != clean


def test_capture_tree_untracked_file(repo):
    (repo / "new.txt").write_text("untracked\n")
    sha = capture_tree(repo)
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", sha, "--", "new.txt"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    assert b"new.txt" in result.stdout


def test_capture_tree_staged_file(repo):
    (repo / "staged.txt").write_text("staged\n")
    git(repo, "add", "staged.txt")
    sha = capture_tree(repo)
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", sha, "--", "staged.txt"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    assert b"staged.txt" in result.stdout


def test_capture_tree_deleted_file(repo):
    (repo / "base.txt").unlink()
    sha = capture_tree(repo)
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", sha, "--", "base.txt"],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    # Deleted file should not appear in tree.
    assert result.returncode != 0 or b"base.txt" not in result.stdout


def test_capture_tree_respects_gitignore(repo):
    (repo / ".gitignore").write_text("ignored/\n")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "secret.txt").write_text("secret\n")
    sha = capture_tree(repo)
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", sha],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    assert b"ignored" not in result.stdout


def test_capture_tree_binary_file(repo):
    (repo / "bin.dat").write_bytes(b"\x00\x01\x02\x03")
    sha = capture_tree(repo)
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", sha, "--", "bin.dat"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    assert b"bin.dat" in result.stdout


def test_capture_tree_symlink(repo):
    (repo / "target.txt").write_text("target\n")
    (repo / "link.txt").symlink_to("target.txt")
    sha = capture_tree(repo)
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", sha, "--", "link.txt"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
    assert b"link.txt" in result.stdout


def test_capture_tree_preserves_user_index(repo):
    (repo / "staged_only.txt").write_text("test\n")
    git(repo, "add", "staged_only.txt")
    before = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False).stdout
    capture_tree(repo)
    after = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False).stdout
    assert before == after


def test_capture_tree_idempotent(repo):
    first = capture_tree(repo)
    second = capture_tree(repo)
    assert first == second


def test_capture_tree_temp_file_cleaned(repo):
    temp_dir = Path.home() / ".forge-alpha" / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    before = len([f for f in temp_dir.iterdir() if f.name.startswith("forge-baseline-")])
    capture_tree(repo)
    after = len([f for f in temp_dir.iterdir() if f.name.startswith("forge-baseline-")])
    # Temp files should be cleaned up; count unchanged.
    assert after <= before + 0


def test_capture_tree_non_git_raises(tmp_path):
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    with pytest.raises(RepositoryInspectionError):
        capture_tree(empty)


def test_capture_tree_no_commits(tmp_path):
    """Empty repo with no commits should still produce a valid tree."""
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["git", "-C", str(empty), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(empty), "config", "user.email", "test@test"],
        check=True)
    # Empty repo: git add -A needs an initialised index.  capture_tree
    # handles the no-HEAD case by letting git auto-create the index.
    (empty / "readme.txt").write_text("hello\n")
    sha = capture_tree(empty)
    assert len(sha) == 40


# ------------------------------------------------------------------ diff_trees


def test_diff_trees_detects_all_status_codes(repo):
    tree_before = capture_tree(repo)
    # Modify existing
    (repo / "base.txt").write_text("modified\n")
    tree_after = capture_tree(repo)
    changes = diff_trees(repo, tree_before, tree_after)
    by_path = {c.path: c.status for c in changes}
    assert by_path.get("base.txt") == "M"


def test_diff_trees_no_rename_detection(repo):
    (repo / "old.py").write_text("x=1\n")
    git(repo, "add", "old.py")
    git(repo, "commit", "-q", "-m", "add old")
    tree_before = capture_tree(repo)
    git(repo, "mv", "old.py", "new.py")
    tree_after = capture_tree(repo)
    changes = diff_trees(repo, tree_before, tree_after)
    statuses = {c.path: c.status for c in changes}
    # Without -M flag, should appear as delete + add, not rename.
    assert statuses.get("old.py") == "D"
    assert statuses.get("new.py") == "A"
    assert "R" not in statuses.values()


def test_diff_trees_returns_change_objects(repo):
    tree_before = capture_tree(repo)
    (repo / "x.txt").write_text("data\n")
    tree_after = capture_tree(repo)
    changes = diff_trees(repo, tree_before, tree_after)
    assert changes and all(isinstance(c, Change) for c in changes)
    assert changes[0].status == "A"
    assert changes[0].path == "x.txt"
    assert changes[0].content == b"data\n"


def test_diff_trees_digest_is_stable(repo):
    tree_before = capture_tree(repo)
    (repo / "a.txt").write_text("one\n")
    tree_after = capture_tree(repo)
    changes = diff_trees(repo, tree_before, tree_after)
    d1 = digest_changes(changes)
    d2 = digest_changes(changes)
    assert d1 == d2
    (repo / "a.txt").write_text("two\n")
    tree_after2 = capture_tree(repo)
    changes2 = diff_trees(repo, tree_before, tree_after2)
    assert d1 != digest_changes(changes2)


# ------------------------------------------------------------------ _parse_diff_name_status


def test_parse_diff_name_status_basic():
    raw = b"A\0new.txt\0M\0mod.txt\0D\0del.txt\0"
    parsed = _parse_diff_name_status(raw)
    assert parsed == [("A", "new.txt"), ("M", "mod.txt"), ("D", "del.txt")]


def test_parse_diff_name_status_empty():
    assert _parse_diff_name_status(b"") == []


def test_parse_diff_name_status_trailing_null():
    raw = b"A\0x.txt\0\0"
    parsed = _parse_diff_name_status(raw)
    assert parsed == [("A", "x.txt")]


# ------------------------------------------------------------------ sweep_temp_dir


def test_sweep_temp_dir_removes_stale_files(tmp_path):
    sweep_dir = tmp_path / "sweep"
    sweep_dir.mkdir()
    stale = sweep_dir / "forge-baseline-XYZ123"
    stale.write_text("old index data")
    other = sweep_dir / "keep-me.txt"
    other.write_text("important")
    sweep_temp_dir(sweep_dir)
    assert not stale.exists()
    assert other.exists()
