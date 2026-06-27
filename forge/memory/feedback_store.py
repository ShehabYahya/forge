from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .._lock import flock_exclusive


class FeedbackStore:
    """Append-only JSONL store for finish-time card ratings (memory_feedback.jsonl)."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self.clock = clock

    def _timestamp(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).isoformat().replace("+00:00", "Z")

    def append_feedback(self, task_id: str, card_id: str, rating: str,
                        reason: str = "") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "task_id": task_id,
            "card_id": card_id,
            "rating": rating,
            "reason": reason,
            "timestamp": self._timestamp(),
        }
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with self.path.open("a+", encoding="utf-8") as stream:
            flock_exclusive(stream)
            stream.seek(0, os.SEEK_END)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def read_feedback(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return records
