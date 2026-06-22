from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import fcntl


class TelemetryWriter:
    def __init__(self, path: Path, max_bytes: int = 2_000_000) -> None:
        self.path = path
        self.max_bytes = max_bytes

    def append(self, value: dict[str, Any]) -> str | None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a+", encoding="utf-8") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                stream.seek(0, os.SEEK_END)
                if stream.tell() >= self.max_bytes:
                    return "telemetry capacity reached; event was not written"
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return None
        except OSError as exc:
            return f"telemetry write failed: {exc}"

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                fcntl.flock(stream, fcntl.LOCK_SH)
                for line in stream:
                    try:
                        value = json.loads(line)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                    if isinstance(value, dict):
                        records.append(value)
        except OSError:
            return []
        return records
