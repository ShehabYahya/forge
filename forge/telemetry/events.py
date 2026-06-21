from __future__ import annotations

from typing import Any


def event(name: str, task_id: str | None, timestamp: str, **fields: Any) -> dict[str, Any]:
    return {"schema_version": 1, "event": name, "task_id": task_id, "timestamp": timestamp, **fields}

