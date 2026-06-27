from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .._lock import flock_exclusive


class ReviewLog:
    """Append-only JSONL log for /review-memory operations (memory_review_log.jsonl).

    Crash safety: a ``batch_started`` record is written before applying any
    operations and a ``batch_completed`` record after.  An orphaned batch (started
    without a matching completed) is detected by :meth:`last_batch_orphaned`.
    """

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.path = path
        self.clock = clock

    def _timestamp(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).isoformat().replace("+00:00", "Z")

    def _append(self, record: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with self.path.open("a+", encoding="utf-8") as stream:
            flock_exclusive(stream)
            stream.seek(0, os.SEEK_END)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    def append_log(self, record: dict[str, Any]) -> None:
        self._append(record)

    def append_batch_started(self, batch_id: str, op_count: int,
                             op_types: list[str]) -> None:
        self._append({
            "event": "batch_started",
            "batch_id": batch_id,
            "op_count": op_count,
            "op_types": list(op_types),
            "timestamp": self._timestamp(),
        })

    def append_batch_completed(self, batch_id: str,
                               results: list[dict[str, Any]] | None = None) -> None:
        self._append({
            "event": "batch_completed",
            "batch_id": batch_id,
            "results": results or [],
            "timestamp": self._timestamp(),
        })

    def append_maintenance_failed(self, reason: str) -> None:
        self._append({
            "event": "maintenance_failed",
            "reason": reason,
            "timestamp": self._timestamp(),
        })

    def append_recommendation_shown(self, reason: str, epoch: float) -> None:
        self._append({
            "event": "recommendation_shown",
            "reason": reason,
            "epoch": float(epoch),
            "timestamp": self._timestamp(),
        })

    def last_recommendation_shown(self) -> float | None:
        """Return the epoch of the last ``recommendation_shown`` event, or None."""
        return self._last_epoch("recommendation_shown")

    def append_update_check(self, epoch: float, update_available: bool,
                            latest_version: str | None = None) -> None:
        self._append({
            "event": "update_check",
            "epoch": float(epoch),
            "update_available": update_available,
            "latest_version": latest_version,
            "timestamp": self._timestamp(),
        })

    def append_update_shown(self, epoch: float, latest_version: str) -> None:
        self._append({
            "event": "update_shown",
            "epoch": float(epoch),
            "latest_version": latest_version,
            "timestamp": self._timestamp(),
        })

    def last_update_check(self) -> tuple[float | None, bool, str | None]:
        """Return (epoch, update_available, latest_version) of the last update_check event."""
        records = self._read_all()
        for record in reversed(records):
            if record.get("event") == "update_check":
                epoch = record.get("epoch")
                if isinstance(epoch, (int, float)):
                    available = bool(record.get("update_available", False))
                    ver = record.get("latest_version")
                    return float(epoch), available, str(ver) if ver else None
        return None, False, None

    def last_update_shown(self) -> float | None:
        """Return the epoch of the last ``update_shown`` event, or None."""
        return self._last_epoch("update_shown")

    def _last_epoch(self, event_name: str) -> float | None:
        records = self._read_all()
        for record in reversed(records):
            if record.get("event") == event_name:
                epoch = record.get("epoch")
                if isinstance(epoch, (int, float)):
                    return float(epoch)
        return None

    def _read_all(self) -> list[dict[str, Any]]:
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

    def last_batch_orphaned(self) -> tuple[bool, dict[str, Any] | None]:
        records = self._read_all()
        completed: set[str] = set()
        started_records: list[dict[str, Any]] = []
        for record in records:
            event = record.get("event")
            batch_id = record.get("batch_id")
            if event == "batch_started" and batch_id is not None:
                started_records.append(record)
            elif event == "batch_completed" and batch_id is not None:
                completed.add(batch_id)
        orphaned = [r for r in started_records if r.get("batch_id") not in completed]
        if not orphaned:
            return (False, None)
        return (True, orphaned[-1])
