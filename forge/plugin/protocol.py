from __future__ import annotations

from pathlib import Path
from importlib.resources import files
from typing import Any

from ..config import load_config
from ..context.governor import ContextGovernor, GovernorCapabilities
from ..service import ForgeService

SCHEMA_VERSION = 1
HIDDEN_OPERATIONS = frozenset({
    "get_active_task",
    "observe_tool_before",
    "observe_tool_after",
    "record_tool_event",
    "start_memory_maintenance",
    "get_maintenance_context",
    "apply_memory_review_batch",
    "finish_memory_maintenance",
    "memory_maintenance_recommendation",
})
MAINTENANCE_OPERATIONS = frozenset({
    "start_memory_maintenance",
    "get_maintenance_context",
    "apply_memory_review_batch",
    "finish_memory_maintenance",
    "memory_maintenance_recommendation",
})
SESSION_MODE_NORMAL = "normal"
SESSION_MODE_MEMORY_REVIEW = "memory_review"


def _review_memory_skill() -> str:
    return files("forge").joinpath("skills/review-memory/SKILL.md").read_text(encoding="utf-8")


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
        self._session_modes: dict[str, str] = {}
        self._maintenance_cache: dict[str, Any] = {}
        self._maintenance_owner: str | None = None

    # ----------------------------------------------------------- session modes

    def session_mode(self, host_session_id: str | None) -> str:
        if not host_session_id:
            return SESSION_MODE_NORMAL
        return self._session_modes.get(host_session_id, SESSION_MODE_NORMAL)

    def _set_session_mode(self, host_session_id: str | None, mode: str) -> None:
        if not host_session_id:
            return
        if mode == SESSION_MODE_NORMAL:
            self._session_modes.pop(host_session_id, None)
        else:
            self._session_modes[host_session_id] = mode

    def _exit_maintenance_mode(self, host_session_id: str | None) -> None:
        self._set_session_mode(host_session_id, SESSION_MODE_NORMAL)
        if host_session_id and self._maintenance_owner == host_session_id:
            self._maintenance_owner = None

    # --------------------------------------------------------- maintenance service

    def _maintenance_service(self, host_session_id: str | None):
        cache_key = host_session_id or "__global__"
        if cache_key in self._maintenance_cache:
            return self._maintenance_cache[cache_key]
        from ..memory.maintenance_service import MaintenanceService

        config = load_config(self.service.runtime_root)
        store = self.service.memory
        task_store = self.service.tasks
        telemetry_path = self.service.telemetry.path
        svc = MaintenanceService(store, config, task_store=task_store,
                                 telemetry_path=telemetry_path,
                                 clock=self.service.clock)
        self._maintenance_cache[cache_key] = svc
        return svc

    def handle(self, wire: dict[str, Any]) -> dict[str, Any]:
        if wire.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported plugin protocol version")
        operation = wire.get("operation")
        if operation not in HIDDEN_OPERATIONS:
            raise ValueError("unknown plugin operation")
        payload = wire.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("plugin payload must be an object")
        if operation in MAINTENANCE_OPERATIONS:
            return self._handle_maintenance(operation, payload)
        if operation == "get_active_task":
            task = self.service._bound_task(payload.get("host_session_id"))
            return self._wire(task.task_id if task else None, "allow", "active task resolved" if task else "no active task")
        task_id = str(payload.get("task_id", ""))
        task = self.service.tasks.get(task_id)
        if not task:
            return self._wire(None, "warn", "no active Forge Alpha task", capability_limited=True)
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

    # --------------------------------------------------------- maintenance ops

    def _handle_maintenance(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        host_session_id = payload.get("host_session_id")
        if operation == "start_memory_maintenance":
            if not isinstance(host_session_id, str) or not host_session_id:
                return self._maintenance_wire(False, {"mode": SESSION_MODE_NORMAL},
                                              "host_session_id is required")
            if self._maintenance_owner not in {None, host_session_id}:
                return self._maintenance_wire(
                    False,
                    self._maintenance_payload(host_session_id, {}),
                    "another memory maintenance session is active",
                )
            self._maintenance_owner = host_session_id
            self._set_session_mode(host_session_id, SESSION_MODE_MEMORY_REVIEW)
            return self._maintenance_wire(True, self._maintenance_payload(
                host_session_id, {
                    "mode": SESSION_MODE_MEMORY_REVIEW,
                    "review_skill": _review_memory_skill(),
                }),
                                          "maintenance mode entered")
        if operation == "memory_maintenance_recommendation":
            svc = self._maintenance_service(host_session_id)
            return self._maintenance_wire(True, self._maintenance_payload(
                host_session_id, svc.memory_maintenance_recommendation()),
                                          "recommendation computed")
        if operation == "get_maintenance_context":
            svc = self._maintenance_service(host_session_id)
            return self._maintenance_wire(True, self._maintenance_payload(
                host_session_id, svc.get_maintenance_context()),
                                          "maintenance context")
        if operation == "apply_memory_review_batch":
            # Defense in depth: refuse unless the session is in memory_review mode.
            if self.session_mode(host_session_id) != SESSION_MODE_MEMORY_REVIEW:
                return self._maintenance_wire(
                    False, self._maintenance_payload(
                        host_session_id,
                        {"applied_count": 0, "rejected_count": 0, "results": []}),
                    "not allowed outside memory_review mode",
                )
            svc = self._maintenance_service(host_session_id)
            operations = payload.get("operations")
            if not isinstance(operations, list):
                return self._maintenance_wire(
                    False, self._maintenance_payload(
                        host_session_id,
                        {"applied_count": 0, "rejected_count": 0, "results": []}),
                    "operations must be a list",
                )
            return self._maintenance_wire(True, self._maintenance_payload(
                host_session_id, svc.apply_memory_review_batch(operations)),
                                          "batch applied")
        if operation == "finish_memory_maintenance":
            status = payload.get("status") or "completed"
            reason = str(payload.get("reason") or "")
            svc = self._maintenance_service(host_session_id)
            result = svc.finish_memory_maintenance(status, reason)
            # Auto-exit maintenance mode regardless of status (spec lines 641-645).
            self._exit_maintenance_mode(host_session_id)
            return self._maintenance_wire(result.get("ok", True),
                                          self._maintenance_payload(host_session_id, result),
                                          "maintenance finished")
        # Unreachable: MAINTENANCE_OPERATIONS is a closed set.
        raise ValueError("unknown maintenance operation")  # pragma: no cover

    def _maintenance_payload(self, host_session_id: str | None,
                             payload: dict[str, Any]) -> dict[str, Any]:
        config = load_config(self.service.runtime_root)
        return {
            **payload,
            "mode": self.session_mode(host_session_id),
            "allowed_tools": list(config.memory.maintenance.review.allow),
            "blocked_tools": list(config.memory.maintenance.review.deny),
        }

    @staticmethod
    def _maintenance_wire(ok: bool, payload: dict[str, Any], reason: str) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "ok": ok, "decision": "allow" if ok else "block",
                "reason": reason, "payload": payload, "replacement_output": None,
                "user_message": None, "capability_limited": False}

    @staticmethod
    def _wire(task_id: str | None, decision: str, reason: str, replacement_output: str | None = None,
              capability_limited: bool = False) -> dict[str, Any]:
        return {"schema_version": 1, "ok": True, "task_id": task_id, "decision": decision,
                "reason": reason, "replacement_output": replacement_output, "user_message": None,
                "capability_limited": capability_limited}
