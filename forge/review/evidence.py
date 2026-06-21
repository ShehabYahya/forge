from __future__ import annotations

from typing import Any


def classify_evidence(reported: list[dict[str, Any]] | None) -> str:
    if not reported:
        return "not_run"
    statuses = {str(item.get("status", "")).lower() for item in reported}
    if statuses & {"failed", "fail", "error"}:
        return "reported_failed"
    if statuses & {"passed", "pass", "ok", "success"}:
        return "reported_passed"
    return "unknown"

