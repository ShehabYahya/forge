from pathlib import Path
import subprocess

from forge.review.diff import capture_changes, digest_changes


def git(repo: Path, *args: str):
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE)


def test_detects_staged_unstaged_deleted_renamed_and_untracked(repo):
    (repo / "staged.txt").write_text("old\n")
    (repo / "delete.txt").write_text("d\n")
    (repo / "rename.txt").write_text("r\n")
    git(repo, "add", "staged.txt", "delete.txt", "rename.txt")
    git(repo, "commit", "-q", "-m", "fixtures")
    (repo / "base.txt").write_text("changed\n")
    (repo / "staged.txt").write_text("new\n")
    git(repo, "add", "staged.txt")
    (repo / "delete.txt").unlink()
    git(repo, "mv", "rename.txt", "renamed.txt")
    (repo / "untracked.txt").write_text("u\n")
    changes = {change.path: change.status for change in capture_changes(repo)}
    assert changes["base.txt"] == ".M"
    assert changes["staged.txt"] == "M."
    assert "D" in changes["delete.txt"]
    assert "R" in changes["renamed.txt"]
    assert changes["untracked.txt"] == "??"


def test_digest_is_stable_and_changes_with_content(repo):
    path = repo / "x.txt"
    path.write_text("one\n")
    first = digest_changes(capture_changes(repo))
    assert first == digest_changes(capture_changes(repo))
    path.write_text("two\n")
    assert first != digest_changes(capture_changes(repo))
