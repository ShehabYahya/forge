from __future__ import annotations

from pathlib import Path
from importlib.resources import files
from typing import Any

from ..config import load_config
from ..context.governor import ContextGovernor, GovernorCapabilities
from ..service import ForgeService
from .session_state import SessionStateStore

SCHEMA_VERSION = 1
HIDDEN_OPERATIONS = frozenset({
    "get_active_task",
    "observe_tool_before",
    "record_tool_event",
    "session_digest",
    "start_memory_maintenance",
    "get_maintenance_context",
    "apply_memory_review_batch",
    "finish_memory_maintenance",
    "memory_maintenance_recommendation",
    "mark_recommendation_shown",
    "check_update",
    "mark_update_shown",
})
MAINTENANCE_OPERATIONS = frozenset({
    "start_memory_maintenance",
    "get_maintenance_context",
    "apply_memory_review_batch",
    "finish_memory_maintenance",
    "memory_maintenance_recommendation",
    "mark_recommendation_shown",
    "check_update",
    "mark_update_shown",
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
        self._state_store = SessionStateStore(service.runtime_root / "plugin_session_state.json")
        persisted = self._state_store.load()
        self._session_modes: dict[str, str] = persisted["session_modes"]
        self._maintenance_cache: dict[str, Any] = {}
        self._maintenance_owner: str | None = persisted["maintenance_owner"]
        self._maintenance_owner_since: float | None = persisted["maintenance_owner_since"]
        self._maintenance_epoch: int = persisted.get("maintenance_epoch", 0)
        self._persist_warning: str | None = None

    def _persist_state(self) -> None:
        try:
            self._state_store.save(self._session_modes, self._maintenance_owner,
                                   self._maintenance_owner_since, self._maintenance_epoch)
        except OSError as exc:
            self._persist_warning = str(exc)

    def _reload_persisted(self) -> dict[str, Any]:
        """Re-read the persisted state from disk. Returns the full load() dict."""
        return self._state_store.load()

    def reload(self) -> None:
        persisted = self._state_store.load()
        raw_modes = persisted.get("session_modes", {})
        modes = raw_modes if isinstance(raw_modes, dict) else {}
        self._session_modes = {str(k): str(v) for k, v in modes.items() if isinstance(v, str)}
        self._maintenance_owner = persisted["maintenance_owner"]
        self._maintenance_owner_since = persisted["maintenance_owner_since"]
        self._maintenance_epoch = persisted.get("maintenance_epoch", 0)

    # ----------------------------------------------------------- session modes

    def session_mode(self, host_session_id: str | None) -> str:
        if not host_session_id:
            return SESSION_MODE_NORMAL
        return self._session_modes.get(host_session_id, SESSION_MODE_NORMAL)

    def _set_session_mode(self, host_session_id: str | None, mode: str, persist: bool = True) -> None:
        if not host_session_id:
            return
        if mode == SESSION_MODE_NORMAL:
            self._session_modes.pop(host_session_id, None)
        else:
            self._session_modes[host_session_id] = mode
        if persist:
            self._persist_state()

    def _exit_maintenance_mode(self, host_session_id: str | None, persist: bool = True) -> None:
        self._set_session_mode(host_session_id, SESSION_MODE_NORMAL, persist=persist)
        if host_session_id and self._maintenance_owner == host_session_id:
            self._maintenance_owner = None
            self._maintenance_owner_since = None
            if persist:
                self._persist_state()

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

    # --------------------------------------------------------- lease helpers

    def _now(self) -> float:
        return self.service.clock()

    def _ttl(self) -> float:
        config = load_config(self.service.runtime_root)
        return float(config.memory.maintenance.review.session_lock_ttl_seconds)

    @staticmethod
    def _is_stale(owner: str | None, since: float | None, now: float, ttl: float) -> bool:
        """A held lock is stale if the owner is set but the timestamp is absent
        or the lease has expired beyond the TTL."""
        if owner is None:
            return False
        if since is None:
            return True
        return (now - since) > ttl

    def _lease_state(self, caller: str | None, owner: str | None,
                     since: float | None, epoch: int, epoch_match: bool, ttl: float) -> str:
        if owner is None:
            return "available"
        if caller is not None and owner == caller and epoch_match:
            if self._is_stale(owner, since, self._now(), ttl):
                return "expired"
            return "active"
        if self._is_stale(owner, since, self._now(), ttl):
            return "expired"
        if owner != caller:
            return "not_owner"
        if not epoch_match:
            return "reclaimed"
        return "active"

    # -------------------------------------------------------- active-session fence

    def _ensure_active_session(self, caller: str | None,
                                payload: dict[str, Any],
                                strict_epoch: bool = True) -> dict[str, Any] | None:
        """Verify the caller owns the lock and the lease has not expired.

        When *strict_epoch* is True (the default, used by apply_batch), the
        caller must also present a matching epoch — this prevents a displaced
        session from writing batches after reclaim. For finish, strict_epoch
        is False since the primary guard is ownership + freshness; a
        cross-restart finish (where the adapter lost its in-memory epoch) is
        still safe as long as nobody else claimed the lock.

        Returns ``None`` on success, or a blocking error dict on failure.

        Must be called inside a ``SessionStateStore.transaction()`` so that the
        persisted state read is fresh and atomic with the subsequent mutation.
        """
        config = load_config(self.service.runtime_root)
        ttl = float(config.memory.maintenance.review.session_lock_ttl_seconds)
        now = self._now()

        # Reload persisted state fresh under the transaction lock.
        persisted = self._reload_persisted()
        owner = persisted["maintenance_owner"]
        since = persisted["maintenance_owner_since"]
        epoch = persisted.get("maintenance_epoch", 0)

        caller_epoch = payload.get("epoch")
        # Legacy transition: epoch==0 + payload lacks epoch → allow
        if strict_epoch:
            legacy = (epoch == 0 and caller_epoch is None)
            epoch_match = legacy or (isinstance(caller_epoch, int) and caller_epoch == epoch)
        else:
            # For finish: epoch is advisory; ownership + freshness is enough.
            epoch_match = True

        lease = self._lease_state(caller, owner, since, epoch, epoch_match, ttl)

        if lease != "active":
            stale_in = 0.0
            if since is not None and not self._is_stale(owner, since, now, ttl):
                stale_in = max(0.0, ttl - (now - since))
            return self._maintenance_wire(
                False,
                self._maintenance_payload(caller, {
                    "lease_state": lease,
                    "owner": owner,
                    "owner_since": since,
                    "stale_in_seconds": stale_in,
                    "ttl_seconds": ttl,
                    "epoch": epoch,
                }),
                "maintenance session fence check failed: " + lease,
            )

        # Sync in-memory state from the transaction-reloaded view.
        self._maintenance_owner = owner
        self._maintenance_owner_since = since
        self._maintenance_epoch = epoch
        self._session_modes = persisted["session_modes"]
        return None

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
        if operation == "session_digest":
            task = self.service._bound_task(payload.get("host_session_id"))
            if task:
                digest = payload.get("digest")
                if isinstance(digest, dict):
                    task.session_digest = digest
                    self.service.tasks.append(task)
                return self._wire(task.task_id, "allow", "digest stored")
            return self._wire(None, "allow", "no active task for digest")
        task_id = str(payload.get("task_id", ""))
        task = self.service.tasks.get(task_id)
        if not task:
            return self._wire(None, "warn", "no active Forge task", capability_limited=True)
        if operation == "record_tool_event":
            warning = self.service._emit("plugin_tool_event", task_id, tool_name=str(payload.get("tool_name", "")))
            return self._wire(task_id, "allow", warning or "tool event recorded")
        governor = self._governors.setdefault(
            task_id,
            ContextGovernor(self.mode, Path(task.repo_root), self.capabilities,
                            clock=self.service.clock),
        )
        if operation == "observe_tool_before":
            decision = governor.before(task_id, str(payload.get("tool_name", "")), payload.get("arguments", {}))
        else:
            raise ValueError(f"unknown observe operation: {operation}")
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
            return self._start_maintenance(host_session_id, payload)

        if operation == "memory_maintenance_recommendation":
            svc = self._maintenance_service(host_session_id)
            return self._maintenance_wire(True, self._maintenance_payload(
                host_session_id, svc.memory_maintenance_recommendation()),
                                          "recommendation computed")
        if operation == "mark_recommendation_shown":
            svc = self._maintenance_service(host_session_id)
            reason = str(payload.get("reason") or "")
            return self._maintenance_wire(True, self._maintenance_payload(
                host_session_id, svc.mark_recommendation_shown(reason)),
                                          "recommendation marked shown")
        if operation == "check_update":
            svc = self._maintenance_service(host_session_id)
            return self._maintenance_wire(True, self._maintenance_payload(
                host_session_id, svc.check_update()),
                                          "update check")
        if operation == "mark_update_shown":
            svc = self._maintenance_service(host_session_id)
            latest_version = str(payload.get("latest_version") or "")
            return self._maintenance_wire(True, self._maintenance_payload(
                host_session_id, svc.mark_update_shown(latest_version)),
                                          "update shown marked")
        if operation == "get_maintenance_context":
            svc = self._maintenance_service(host_session_id)
            return self._maintenance_wire(True, self._maintenance_payload(
                host_session_id, svc.get_maintenance_context()),
                                          "maintenance context")
        if operation == "apply_memory_review_batch":
            return self._apply_batch(host_session_id, payload)

        if operation == "finish_memory_maintenance":
            return self._finish_maintenance(host_session_id, payload)

        # Unreachable: MAINTENANCE_OPERATIONS is a closed set.
        raise ValueError("unknown maintenance operation")  # pragma: no cover

    # ---------------------------------------------------- start (lease acquire)

    def _start_maintenance(self, caller: str, payload: dict[str, Any]) -> dict[str, Any]:
        config = load_config(self.service.runtime_root)
        ttl = float(config.memory.maintenance.review.session_lock_ttl_seconds)
        force_enabled = bool(config.memory.maintenance.review.session_lock_force_enabled)
        force = bool(payload.get("force")) and force_enabled

        with self._state_store.transaction() as state:
            now = self._now()
            owner = state.get("maintenance_owner")
            since = state.get("maintenance_owner_since")
            epoch: int = state.get("maintenance_epoch", 0)

            # --- Idempotent re-entry: caller already owns the lock.
            if owner == caller:
                since = now
                state["maintenance_owner_since"] = since
                state["session_modes"] = state.get("session_modes", {})
                state["session_modes"][caller] = SESSION_MODE_MEMORY_REVIEW
                self._maintenance_owner = owner
                self._maintenance_owner_since = since
                self._maintenance_epoch = epoch
                self._session_modes = state["session_modes"]
                return self._maintenance_wire(True, self._maintenance_payload(caller, {
                    "mode": SESSION_MODE_MEMORY_REVIEW,
                    "review_skill": _review_memory_skill(),
                    "lease_state": "active",
                    "epoch": epoch,
                }), "maintenance mode re-entered")

            # --- Lock is held by another session.
            if owner is not None:
                # Force reclaim (operator override) or stale auto-reclaim.
                if force or self._is_stale(owner, since, now, ttl):
                    reason = "reclaimed (forced)" if force else "reclaimed (stale)"
                    epoch += 1
                    state["maintenance_owner"] = caller
                    state["maintenance_owner_since"] = now
                    state["maintenance_epoch"] = epoch
                    # Clear previous owner's session state.
                    modes = state.get("session_modes", {})
                    if isinstance(modes, dict):
                        modes.pop(owner, None)
                    modes[caller] = SESSION_MODE_MEMORY_REVIEW
                    state["session_modes"] = modes
                    self._maintenance_owner = caller
                    self._maintenance_owner_since = now
                    self._maintenance_epoch = epoch
                    self._session_modes = modes
                    self._maintenance_cache.pop(owner, None)
                    return self._maintenance_wire(True, self._maintenance_payload(caller, {
                        "mode": SESSION_MODE_MEMORY_REVIEW,
                        "review_skill": _review_memory_skill(),
                        "lease_state": "reclaimed",
                        "epoch": epoch,
                        "reclaim_reason": reason,
                    }), reason)

                # Stubborn block — not stale, not forced.
                stale_in = max(0.0, ttl - (now - (since or now)))
                return self._maintenance_wire(
                    False,
                    self._maintenance_payload(caller, {
                        "owner": owner,
                        "owner_since": since,
                        "stale_in_seconds": stale_in,
                        "ttl_seconds": ttl,
                        "lease_state": "not_owner",
                    }),
                    "another memory maintenance session is active",
                )

            # --- No current owner — fresh acquire.
            epoch += 1
            state["maintenance_owner"] = caller
            state["maintenance_owner_since"] = now
            state["maintenance_epoch"] = epoch
            modes = state.get("session_modes", {})
            if isinstance(modes, dict):
                modes[caller] = SESSION_MODE_MEMORY_REVIEW
            state["session_modes"] = modes
            self._maintenance_owner = caller
            self._maintenance_owner_since = now
            self._maintenance_epoch = epoch
            self._session_modes = modes
            return self._maintenance_wire(True, self._maintenance_payload(caller, {
                "mode": SESSION_MODE_MEMORY_REVIEW,
                "review_skill": _review_memory_skill(),
                "lease_state": "active",
                "epoch": epoch,
            }), "maintenance mode entered")

    # ----------------------------------------------------------- apply (fence)

    def _apply_batch(self, caller: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        # Defense in depth: refuse unless the session is in memory_review mode.
        if self.session_mode(caller) != SESSION_MODE_MEMORY_REVIEW:
            return self._maintenance_wire(
                False, self._maintenance_payload(
                    caller,
                    {"applied_count": 0, "rejected_count": 0, "results": []}),
                "not allowed outside memory_review mode",
            )

        # Fence check inside a transaction — ensures epoch and ownership match.
        with self._state_store.transaction() as state:
            fence_err = self._ensure_active_session(caller, payload)
            if fence_err is not None:
                return fence_err

            operations = payload.get("operations")
            if not isinstance(operations, list):
                return self._maintenance_wire(
                    False, self._maintenance_payload(
                        caller,
                        {"applied_count": 0, "rejected_count": 0, "results": []}),
                    "operations must be a list",
                )

            svc = self._maintenance_service(caller)
            result = svc.apply_memory_review_batch(operations)

            # Heartbeat: extend lease on success.
            now = self._now()
            state["maintenance_owner_since"] = now
            self._maintenance_owner_since = now

            return self._maintenance_wire(True, self._maintenance_payload(
                caller, {**result, "lease_state": "active"}),
                                          "batch applied")

    # ---------------------------------------------------------- finish (fence)

    def _finish_maintenance(self, caller: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        # Check ownership and epoch before allowing finish.
        # A zombie finish (displaced session) must not evict a newer session
        # and must not write review_log entries via svc.finish_memory_maintenance.
        with self._state_store.transaction() as state:
            fence_err = self._ensure_active_session(caller, payload, strict_epoch=False)
            if fence_err is not None:
                return fence_err

            status = payload.get("status") or "completed"
            reason = str(payload.get("reason") or "")
            svc = self._maintenance_service(caller)
            result = svc.finish_memory_maintenance(status, reason)

            # Exit maintenance mode — only for the verified owner.
            self._exit_maintenance_mode(caller, persist=False)
            # Persist the exit inside the transaction.
            state["maintenance_owner"] = None
            state["maintenance_owner_since"] = None
            state["session_modes"] = {k: v for k, v in state.get("session_modes", {}).items()
                                       if k != caller}

            return self._maintenance_wire(result.get("ok", True),
                                          self._maintenance_payload(caller, result),
                                          "maintenance finished")

    # ------------------------------------------------------------ wire helpers

    def _maintenance_payload(self, host_session_id: str | None,
                             payload: dict[str, Any]) -> dict[str, Any]:
        config = load_config(self.service.runtime_root)
        result = {
            **payload,
            "mode": self.session_mode(host_session_id),
            "allowed_tools": list(config.memory.maintenance.review.allow),
            "blocked_tools": list(config.memory.maintenance.review.deny),
        }
        result.setdefault("epoch", self._maintenance_epoch)
        if self._persist_warning:
            result["persist_warning"] = self._persist_warning
            self._persist_warning = None
        return result

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
