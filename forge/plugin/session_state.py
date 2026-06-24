from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

def _empty_state() -> dict[str, Any]:
    return {
        "session_modes": {},
        "maintenance_owner": None,
        "maintenance_owner_since": None,
        "maintenance_epoch": 0,
    }


class SessionStateStore:
    """Crash-safe persistence for plugin session-mode and maintenance-owner state.

    The persisted shape is ``{"session_modes": {host_session_id: mode},
    "maintenance_owner": str | None, "maintenance_owner_since": float | None,
    "maintenance_epoch": int}``. Reads are tolerant of a missing or
    corrupt file and never raise; writes use the same atomic pattern as
    ``forge.memory.store._write_json`` (mkdir parents, flock, temp file named
    with the pid, fsync, ``os.replace``).
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_state()
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return _empty_state()
        if not text.strip():
            return _empty_state()
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError, TypeError):
            return _empty_state()
        if not isinstance(data, dict):
            return _empty_state()
        raw_modes = data.get("session_modes")
        modes = raw_modes if isinstance(raw_modes, dict) else {}
        clean_modes = {str(k): str(v) for k, v in modes.items() if isinstance(v, str)}
        owner = data.get("maintenance_owner")
        if not isinstance(owner, str):
            owner = None
        owner_since = data.get("maintenance_owner_since")
        if owner_since is not None and not isinstance(owner_since, (int, float)):
            owner_since = None
        epoch = data.get("maintenance_epoch")
        if not isinstance(epoch, int):
            epoch = 0
        return {
            "session_modes": clean_modes,
            "maintenance_owner": owner,
            "maintenance_owner_since": owner_since,
            "maintenance_epoch": epoch,
        }

    def save(self, session_modes: dict[str, str], maintenance_owner: str | None,
             maintenance_owner_since: float | None = None,
             maintenance_epoch: int = 0) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            with tmp.open("w", encoding="utf-8") as stream:
                json.dump({
                    "session_modes": session_modes,
                    "maintenance_owner": maintenance_owner,
                    "maintenance_owner_since": maintenance_owner_since,
                    "maintenance_epoch": maintenance_epoch,
                }, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)

    @contextmanager
    def transaction(self) -> Generator[dict[str, Any], None, None]:
        """Hold ``LOCK_EX`` across a read-modify-write cycle.

        Yields a live state dict (the same shape as ``load()``) that the caller
        may mutate in place. On exit the state is atomically persisted and the
        lock released. Cross-process safety: every lock operation that reads
        then writes must run inside this transaction.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self.load()
            try:
                yield state
            except Exception:
                raise
            else:
                tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
                with tmp.open("w", encoding="utf-8") as stream:
                    json.dump({
                        "session_modes": state.get("session_modes", {}),
                        "maintenance_owner": state.get("maintenance_owner"),
                        "maintenance_owner_since": state.get("maintenance_owner_since"),
                        "maintenance_epoch": state.get("maintenance_epoch", 0),
                    }, stream, sort_keys=True, separators=(",", ":"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, self.path)
