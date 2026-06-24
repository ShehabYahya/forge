from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Any

_EMPTY: dict[str, Any] = {"session_modes": {}, "maintenance_owner": None}


class SessionStateStore:
    """Crash-safe persistence for plugin session-mode and maintenance-owner state.

    The persisted shape is ``{"session_modes": {host_session_id: mode},
    "maintenance_owner": str | None}``. Reads are tolerant of a missing or
    corrupt file and never raise; writes use the same atomic pattern as
    ``forge.memory.store._write_json`` (mkdir parents, flock, temp file named
    with the pid, fsync, ``os.replace``).
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"session_modes": {}, "maintenance_owner": None}
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return {"session_modes": {}, "maintenance_owner": None}
        if not text.strip():
            return {"session_modes": {}, "maintenance_owner": None}
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError, TypeError):
            return {"session_modes": {}, "maintenance_owner": None}
        if not isinstance(data, dict):
            return {"session_modes": {}, "maintenance_owner": None}
        raw_modes = data.get("session_modes")
        modes = raw_modes if isinstance(raw_modes, dict) else {}
        clean_modes = {str(k): str(v) for k, v in modes.items() if isinstance(v, str)}
        owner = data.get("maintenance_owner")
        if not isinstance(owner, str):
            owner = None
        return {"session_modes": clean_modes, "maintenance_owner": owner}

    def save(self, session_modes: dict[str, str], maintenance_owner: str | None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            with tmp.open("w", encoding="utf-8") as stream:
                json.dump({"session_modes": session_modes, "maintenance_owner": maintenance_owner},
                          stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
