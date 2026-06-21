from __future__ import annotations

from pathlib import Path
from typing import Any

from ..context.governor import ContextGovernor, GovernorCapabilities
from ..service import ForgeService

SCHEMA_VERSION = 1
HIDDEN_OPERATIONS = frozenset({"get_active_task", "observe_tool_before", "observe_tool_after", "record_tool_event"})


def request(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation not in HIDDEN_OPERATIONS:
        raise ValueError("unknown plugin operation")
    return {"schema_version": SCHEMA_VERSION, "operation": operation, "payload": payload}


def validate_response(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported plugin protocol version")
    if not isinstance(value.get("ok"), bool):
        raise ValueError("plugin response lacks boolean ok")
    return value


class PluginProtocolBackend:
    """Hidden bridge used by adapters; it is intentionally absent from MCP discovery."""

    def __init__(self, service: ForgeService, mode: str = "report",
                 capabilities: GovernorCapabilities | None = None) -> None:
        self.service = service
        self.mode = mode
        self.capabilities = capabilities or GovernorCapabilities()
        self._governors: dict[str, ContextGovernor] = {}

    def handle(self, wire: dict[str, Any]) -> dict[str, Any]:
        if wire.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported plugin protocol version")
        operation = wire.get("operation")
        if operation not in HIDDEN_OPERATIONS:
            raise ValueError("unknown plugin operation")
        payload = wire.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("plugin payload must be an object")
        if operation == "get_active_task":
            task = self.service._bound_task(payload.get("host_session_id"))
            return self._wire(task.task_id if task else None, "allow", "active task resolved" if task else "no active task")
        task_id = str(payload.get("task_id", ""))
        task = self.service.tasks.get(task_id)
        if not task:
            return self._wire(None, "warn", "no active Forge Alpha task")
        if operation == "record_tool_event":
            warning = self.service._emit("plugin_tool_event", task_id, tool_name=str(payload.get("tool_name", "")))
            return self._wire(task_id, "allow", warning or "tool event recorded")
        governor = self._governors.setdefault(
            task_id,
            ContextGovernor(self.mode, Path(task.repo_root), self.service.results, self.capabilities,
                            clock=self.service.clock),
        )
        if operation == "observe_tool_before":
            decision = governor.before(task_id, str(payload.get("tool_name", "")), payload.get("arguments", {}))
        else:
            decision = governor.after(task_id, str(payload.get("tool_name", "")), str(payload.get("output", "")))
        return self._wire(task_id, decision["decision"], decision["reason"],
                          replacement_output=decision.get("replacement_output"),
                          capability_limited=decision.get("capability_limited", False))

    @staticmethod
    def _wire(task_id: str | None, decision: str, reason: str, replacement_output: str | None = None,
              capability_limited: bool = False) -> dict[str, Any]:
        return {"schema_version": 1, "ok": True, "task_id": task_id, "decision": decision,
                "reason": reason, "replacement_output": replacement_output, "user_message": None,
                "capability_limited": capability_limited}
