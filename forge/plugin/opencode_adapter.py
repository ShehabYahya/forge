from __future__ import annotations

from typing import Any, Callable

from .protocol import request, validate_response


class OpenCodeAdapter:
    """Transport-only adapter. The backend owns all decisions."""

    def __init__(self, transport: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.transport = transport

    def forward(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize(payload)
        try:
            result = validate_response(self.transport(request(operation, normalized)))
        except Exception as exc:
            return {"schema_version": 1, "ok": False, "task_id": None, "decision": "warn",
                    "reason": f"Forge Alpha backend unavailable: {exc}", "replacement_output": None,
                    "user_message": "Forge Alpha adapter is degraded; policy is not actively enforced.",
                    "capability_limited": True}
        return result

    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._normalize(child) for key, child in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._normalize(child) for child in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

