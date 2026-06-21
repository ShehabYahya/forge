from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import fcntl

from .task_state import TaskSnapshot


class TaskStore:
    def __init__(self, path: Path, compact_after: int = 10_000) -> None:
        self.path = path
        self.compact_after = compact_after
        self._cache: dict[str, TaskSnapshot] | None = None
        self.warnings: list[str] = []
        self._records = 0

    def _load(self) -> None:
        self._cache = {}
        self.warnings = []
        self._records = 0
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                self._records += 1
                try:
                    value = json.loads(line)
                    task = TaskSnapshot.from_dict(value)
                    if not task.task_id:
                        raise ValueError("empty task_id")
                    self._cache[task.task_id] = task
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    self.warnings.append(f"skipped corrupt task record at line {number}: {exc}")

    def all(self) -> list[TaskSnapshot]:
        if self._cache is None:
            self._load()
        return list(self._cache.values())  # type: ignore[union-attr]

    def get(self, task_id: str) -> TaskSnapshot | None:
        if self._cache is None:
            self._load()
        return self._cache.get(task_id)  # type: ignore[union-attr]

    def append(self, task: TaskSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(task.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if self._cache is None:
            self._load()
        else:
            self._cache[task.task_id] = TaskSnapshot.from_dict(task.to_dict())
            self._records += 1
        if self._records > self.compact_after:
            self.compact()

    def compact(self) -> None:
        tasks = sorted(self.all(), key=lambda item: item.task_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            for task in tasks:
                stream.write(json.dumps(task.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        self._records = len(tasks)

