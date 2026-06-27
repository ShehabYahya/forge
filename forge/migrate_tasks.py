from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from ._lock import flock_exclusive
from .task_state import TaskSnapshot

STATUS_TO_STATE = {
    "active": "active",
    "completed": "completed",
    "failed": "failed",
}
SCOPE_MAP = {
    "warn": "warning",
    "strict": "strict",
}
def _valid_task_state(state: str) -> str:
    valid = {"active", "review_blocked", "reviewed",
             "completed", "failed", "degraded"}
    if state not in valid:
        raise ValueError(f"unknown task state: {state}")
    return state


def _normalise_iso(ts: str) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).isoformat()
    except (ValueError, TypeError):
        return ts.replace("+00:00", "Z").rstrip("Z") + "Z"


def convert(legacy: dict) -> TaskSnapshot:
    status = legacy.get("status", "active")
    state = STATUS_TO_STATE.get(status)
    if state is None:
        raise ValueError(f"unknown legacy status: {status}")
    scope_mode = SCOPE_MAP.get(legacy.get("scope_policy", "warn"), "warning")

    snapshot_fields = {f.name for f in TaskSnapshot.__dataclass_fields__.values()}

    kwargs: dict = {
        "task_id": legacy.get("task_id", ""),
        "state": _valid_task_state(state),
        "task_text": legacy.get("task_text", ""),
        "repo_root": legacy.get("repo_root", ""),
        "expected_files": legacy.get("expected_files") or [],
        "host_session_id": legacy.get("host_session_id") or None,
        "scope_mode": scope_mode,
        "created_at": _normalise_iso(legacy.get("created_at", "")),
        "updated_at": _normalise_iso(legacy.get("updated_at", "")),
        "schema_version": 1,
    }
    for key in legacy:
        if key in snapshot_fields and key not in kwargs:
            kwargs[key] = legacy[key]
    return TaskSnapshot(**kwargs)


def migrate(sessions_path: str | Path, tasks_path: str | Path,
            tasks_lock_path: str | Path, dry_run: bool = False) -> dict:
    sessions_path = Path(sessions_path)
    tasks_path = Path(tasks_path)
    tasks_lock_path = Path(tasks_lock_path)

    legacy_tasks: list[dict] = []
    with sessions_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                legacy_tasks.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    existing_ids: set[str] = set()
    if tasks_path.exists():
        with tasks_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    tid = data.get("task_id")
                    if tid:
                        existing_ids.add(tid)
                except json.JSONDecodeError:
                    continue

    tasks_path.parent.mkdir(parents=True, exist_ok=True)

    new_entries: list[dict] = []
    skipped_active = 0
    skipped_duplicate = 0
    for legacy in legacy_tasks:
        tid = legacy.get("task_id", "")
        if not tid:
            continue
        if tid in existing_ids:
            skipped_duplicate += 1
            continue
        status = legacy.get("status", "active")
        if status == "active":
            skipped_active += 1
            continue
        try:
            snapshot = convert(legacy)
        except ValueError:
            skipped_active += 1
            continue
        new_entries.append(snapshot.to_dict())
        existing_ids.add(tid)

    count = len(new_entries)
    if dry_run:
        return {"dry_run": True, "migrated": count,
                "skipped_active": skipped_active,
                "skipped_duplicate": skipped_duplicate,
                "entries": new_entries}

    tasks_lock_path.parent.mkdir(parents=True, exist_ok=True)
    with tasks_lock_path.open("a+", encoding="utf-8") as lock_fh:
        flock_exclusive(lock_fh)
        with tasks_path.open("a", encoding="utf-8") as fh:
            for entry in new_entries:
                line = json.dumps(entry, sort_keys=True,
                                  separators=(",", ":")) + "\n"
                fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    return {"dry_run": False, "migrated": count,
            "skipped_active": skipped_active,
            "skipped_duplicate": skipped_duplicate}
