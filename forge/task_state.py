from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = 1
TaskState = Literal["active", "review_blocked", "reviewed", "completed", "failed", "degraded"]
TERMINAL_STATES = frozenset({"completed", "failed", "degraded"})


@dataclass(slots=True)
class TaskSnapshot:
    task_id: str
    state: TaskState
    task_text: str
    repo_root: str
    expected_files: list[str] = field(default_factory=list)
    host_session_id: str | None = None
    scope_mode: str = "strict"
    created_at: str = ""
    updated_at: str = ""
    review_digest: str | None = None
    review: dict[str, Any] | None = None
    terminal_result: dict[str, Any] | None = None
    schema_version: int = SCHEMA_VERSION
    injected_memory_cards: list[str] = field(default_factory=list)
    baseline_tree_id: str | None = None
    baseline_status: str = "unavailable"
    baseline_capture_error: str | None = None
    session_digest: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskSnapshot":
        fields = cls.__dataclass_fields__
        return cls(**{key: value[key] for key in fields if key in value})


def response(task: TaskSnapshot | None, *, ok: bool, warnings: list[str] | None = None,
             required_next_action: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "task_id": task.task_id if task else extra.pop("task_id", None),
        "state": task.state if task else extra.pop("state", None),
        "warnings": warnings or [],
        "required_next_action": required_next_action,
        **extra,
    }

