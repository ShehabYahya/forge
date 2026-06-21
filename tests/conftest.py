from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from forge.service import ForgeService


def run(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    run(root, "init", "-q")
    run(root, "config", "user.email", "tests@example.invalid")
    run(root, "config", "user.name", "Forge Tests")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    run(root, "add", "base.txt")
    run(root, "commit", "-q", "-m", "baseline")
    return root


@pytest.fixture
def service(tmp_path: Path) -> ForgeService:
    counter = iter(range(1000))
    return ForgeService(tmp_path / "runtime", clock=lambda: float(next(counter)),
                        id_factory=lambda seed: "task_test")

