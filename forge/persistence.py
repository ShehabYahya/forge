from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ._lock import flock_exclusive, flock_shared
from .task_state import TaskSnapshot


class TaskStore:
    def __init__(self, path: Path, compact_after: int = 10_000) -> None:
        self.path = path
        self.compact_after = compact_after
        self._cache: dict[str, TaskSnapshot] | None = None
        self.warnings: list[str] = []
        self._records = 0
        self._signature: tuple[int, int, int, int] | None = None

    @property
    def lock_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".lock")

    def _file_signature(self) -> tuple[int, int, int, int] | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

    def _load(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            flock_shared(lock)
            self._load_unlocked()

    def _load_unlocked(self) -> None:
        self._cache = {}
        self.warnings = []
        self._records = 0
        if not self.path.exists():
            self._signature = None
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
        self._signature = self._file_signature()

    def _refresh(self) -> None:
        if self._cache is None or self._signature != self._file_signature():
            self._load()

    def reload(self) -> None:
        self._cache = None
        self._signature = None

    def all(self) -> list[TaskSnapshot]:
        self._refresh()
        return list(self._cache.values())  # type: ignore[union-attr]

    def get(self, task_id: str) -> TaskSnapshot | None:
        self._refresh()
        return self._cache.get(task_id)  # type: ignore[union-attr]

    def append(self, task: TaskSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(task.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            flock_exclusive(lock)
            self._load_unlocked()
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            self._cache[task.task_id] = TaskSnapshot.from_dict(task.to_dict())
            self._records += 1
            self._signature = self._file_signature()
            if self._records > self.compact_after:
                self._compact_unlocked()

    def compact(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            flock_exclusive(lock)
            self._load_unlocked()
            self._compact_unlocked()

    def _compact_unlocked(self) -> None:
        tasks = self.all()
        temporary = self.path.with_suffix(self.path.suffix + f".{os.getpid()}.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            for task in tasks:
                stream.write(json.dumps(task.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        self._records = len(tasks)
        self._signature = self._file_signature()
