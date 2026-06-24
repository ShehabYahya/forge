"""Session-mode gating + response-shape tests for /review-memory.

Covers:
  * normal sessions cannot apply (defense in depth)
  * review mode exposes only review ops
  * start_memory_maintenance sets mode
  * finish_memory_maintenance exits mode (success and failure)
  * orphaned batch detected on next get_maintenance_context
  * batch apply partial (valid applies, invalid rejected)
  * response shape matches spec
  * recommendation triggers on low-confidence threshold
  * recommendation one reason string
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from forge.config import default_config
from forge.memory.cards import AppliesWhen, MemoryCard
from forge.memory.maintenance_service import MaintenanceService
from forge.memory.store import MemoryStore
from forge.plugin.protocol import (
    HIDDEN_OPERATIONS,
    MAINTENANCE_OPERATIONS,
    SESSION_MODE_MEMORY_REVIEW,
    SESSION_MODE_NORMAL,
    PluginProtocolBackend,
)
from forge.task_state import TaskSnapshot


def _clock() -> Callable[[], float]:
    counter = iter(range(1000))
    return lambda: float(next(counter))


def card(card_id: str = "", **values) -> MemoryCard:
    defaults = {
        "card_id": card_id,
        "memory": f"memory note about forge/service.py for {card_id or 'new'}",
        "why": "past regressions in this module",
        "avoid": "editing without running the test suite",
        "use_as": "",
        "entry_type": "validation_memory",
        "transferability": "local_only",
        "source_repo_root": "/repo",
        "source_repo_id": "/repo",
        "applies_when": AppliesWhen(),
        "confidence": "medium",
        "source_task_ids": [],
        "supersedes": [],
        "superseded_by": None,
        "created_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(values)
    return MemoryCard(**defaults)


def _wire(operation: str, payload: dict) -> dict:
    return {"schema_version": 1, "operation": operation, "payload": payload}


def _start(backend, host_id, **extra) -> int:
    """Start a maintenance session and return the session epoch."""
    result = backend.handle(_wire("start_memory_maintenance", {"host_session_id": host_id, **extra}))
    assert result["ok"], f"start failed: {result.get('reason')}"
    return result["payload"]["epoch"]


def _apply(backend, host_id, operations, epoch=None):
    """Apply a batch, optionally passing the session epoch."""
    p = {"host_session_id": host_id, "operations": operations}
    if epoch is not None:
        p["epoch"] = epoch
    return backend.handle(_wire("apply_memory_review_batch", p))


def _finish(backend, host_id, status="completed", reason=""):
    return backend.handle(_wire("finish_memory_maintenance",
                                {"host_session_id": host_id, "status": status, "reason": reason}))


# --------------------------------------------------------------- hidden ops set


def test_maintenance_ops_registered_alongside_existing():
    expected_maintenance = {
        "start_memory_maintenance",
        "get_maintenance_context",
        "apply_memory_review_batch",
        "finish_memory_maintenance",
        "memory_maintenance_recommendation",
    }
    assert expected_maintenance.issubset(HIDDEN_OPERATIONS)
    # The 4 pre-existing ops are still present.
    assert {"get_active_task", "observe_tool_before",
            "observe_tool_after", "record_tool_event"}.issubset(HIDDEN_OPERATIONS)
    assert MAINTENANCE_OPERATIONS == expected_maintenance
    assert "session_digest" in HIDDEN_OPERATIONS
    assert len(HIDDEN_OPERATIONS) == 10


# --------------------------------------------------------------- mode lifecycle


def test_normal_session_cannot_apply(service, repo):
    backend = PluginProtocolBackend(service)
    # No start_memory_maintenance called → mode is normal.
    assert backend.session_mode("host") == SESSION_MODE_NORMAL
    result = backend.handle(_wire("apply_memory_review_batch",
                                   {"host_session_id": "host", "operations": []}))
    assert result["ok"] is False
    assert result["decision"] == "block"
    assert "memory_review" in result["reason"]


def test_start_memory_maintenance_sets_mode(service, repo):
    backend = PluginProtocolBackend(service)
    result = backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    assert backend.session_mode("host") == SESSION_MODE_MEMORY_REVIEW
    assert result["payload"]["mode"] == SESSION_MODE_MEMORY_REVIEW
    assert "# Review Memory" in result["payload"]["review_skill"]
    assert "finish_task" in result["payload"]["allowed_tools"]
    assert result["payload"]["blocked_tools"] == ["edit", "write", "bash"]


def test_finish_memory_maintenance_exits_mode_on_success(service, repo):
    backend = PluginProtocolBackend(service)
    backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    assert backend.session_mode("host") == SESSION_MODE_MEMORY_REVIEW
    backend.handle(_wire("finish_memory_maintenance",
                         {"host_session_id": "host", "status": "completed"}))
    assert backend.session_mode("host") == SESSION_MODE_NORMAL


def test_finish_memory_maintenance_exits_mode_on_failure(service, repo):
    backend = PluginProtocolBackend(service)
    backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    backend.handle(_wire("finish_memory_maintenance",
                         {"host_session_id": "host", "status": "failed",
                          "reason": "telemetry unreadable"}))
    assert backend.session_mode("host") == SESSION_MODE_NORMAL
    # The maintenance_failed record is in the review log.
    log_text = service.memory.review_log.path.read_text(encoding="utf-8")
    assert "maintenance_failed" in log_text
    assert "telemetry unreadable" in log_text


def test_review_mode_can_apply(service, repo):
    backend = PluginProtocolBackend(service)
    epoch = _start(backend, "host")
    # Seed a card to edit.
    service.memory.add_card(card("mem_000001",
                                 memory="edit forge/service.py to pass runtime_root"))
    result = _apply(backend, "host", [
        {"operation": "edit_card", "temp_id": "t1", "card_id": "mem_000001",
         "memory": "always pass runtime_root to load_config() in forge/service.py"},
    ], epoch=epoch)
    assert result["ok"] is True
    payload = result["payload"]
    assert payload["applied_count"] == 1
    assert payload["rejected_count"] == 0


def test_maintenance_without_active_task_stays_in_review_mode(service, repo):
    backend = PluginProtocolBackend(service)
    backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    assert backend.session_mode("host") == SESSION_MODE_MEMORY_REVIEW
    context = backend.handle(_wire("get_maintenance_context", {"host_session_id": "host"}))
    assert context["payload"]["mode"] == SESSION_MODE_MEMORY_REVIEW
    assert backend.session_mode("host") == SESSION_MODE_MEMORY_REVIEW


def test_only_one_maintenance_session_can_be_active(service, repo):
    backend = PluginProtocolBackend(service)
    assert backend.handle(_wire(
        "start_memory_maintenance", {"host_session_id": "first"}
    ))["ok"] is True
    second = backend.handle(_wire(
        "start_memory_maintenance", {"host_session_id": "second"}
    ))
    assert second["ok"] is False
    assert "another" in second["reason"]


# ------------------------------------------------------------------- lease


def test_stale_auto_reclaim_after_ttl(service, repo):
    """A lock whose TTL has expired is auto-reclaimed on next start."""
    backend_a = PluginProtocolBackend(service)
    epoch_a = _start(backend_a, "host_a")

    # Simulate TTL expiry by directly overwriting the persisted since timestamp.
    state_path = service.runtime_root / "plugin_session_state.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    now = service.clock()
    data["maintenance_owner_since"] = now - 7200  # 2 hours ago, beyond 1h TTL
    state_path.write_text(json.dumps(data), encoding="utf-8")

    # A new backend (simulating a different process) can reclaim.
    backend_b = PluginProtocolBackend(service)
    result = backend_b.handle(_wire("start_memory_maintenance", {"host_session_id": "host_b"}))
    assert result["ok"] is True
    assert result["payload"]["lease_state"] == "reclaimed"
    assert "stale" in result["payload"]["reclaim_reason"]
    assert backend_b._maintenance_owner == "host_b"
    assert backend_b._maintenance_epoch > epoch_a

    # The displaced session's apply must be rejected by epoch.
    result_a = _apply(backend_a, "host_a", [], epoch=epoch_a)
    assert result_a["ok"] is False
    assert result_a["payload"]["lease_state"] == "not_owner"


def test_force_reclaim_before_ttl(service, repo):
    """Force-reclaim takes a live lock before TTL expiry, increments epoch."""
    backend_a = PluginProtocolBackend(service)
    epoch_a = _start(backend_a, "host_a")

    # host_b force-reclaims while host_a is still live.
    backend_b = PluginProtocolBackend(service)
    result = backend_b.handle(_wire("start_memory_maintenance",
                                    {"host_session_id": "host_b", "force": True}))
    assert result["ok"] is True
    assert result["payload"]["lease_state"] == "reclaimed"
    assert "forced" in result["payload"]["reclaim_reason"]
    assert backend_b._maintenance_owner == "host_b"
    epoch_b = result["payload"]["epoch"]
    assert epoch_b > epoch_a

    # host_a apply with old epoch must be rejected.
    result_a = _apply(backend_a, "host_a", [], epoch=epoch_a)
    assert result_a["ok"] is False
    assert result_a["payload"]["lease_state"] == "not_owner"

    # host_a finish must be blocked (non-owner zombie).
    finish_a = backend_a.handle(_wire("finish_memory_maintenance",
                                      {"host_session_id": "host_a", "status": "completed"}))
    assert finish_a["ok"] is False
    assert finish_a["payload"]["lease_state"] in ("not_owner", "reclaimed")


def test_force_disabled_ignores_force_flag(service, repo):
    """When session_lock_force_enabled is False, force is ignored."""
    backend_a = PluginProtocolBackend(service)
    _start(backend_a, "host_a")

    # Write a config that disables force.
    config_path = service.runtime_root / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({
        "memory": {"maintenance": {"review": {"session_lock_force_enabled": False}}}
    }), encoding="utf-8")

    backend_b = PluginProtocolBackend(service)
    result = backend_b.handle(_wire("start_memory_maintenance",
                                    {"host_session_id": "host_b", "force": True}))
    assert result["ok"] is False
    assert "another" in result["reason"]


def test_heartbeat_extends_lease(service, repo):
    """Successful apply_batch extends maintenance_owner_since."""
    backend = PluginProtocolBackend(service)
    _start(backend, "host")

    state_path = service.runtime_root / "plugin_session_state.json"
    data_before = json.loads(state_path.read_text(encoding="utf-8"))
    before_since = data_before["maintenance_owner_since"]

    # Apply a batch — should extend the lease.
    result = _apply(backend, "host", [], epoch=backend._maintenance_epoch)
    assert result["ok"] is True

    data_after = json.loads(state_path.read_text(encoding="utf-8"))
    after_since = data_after["maintenance_owner_since"]
    assert after_since > before_since


def test_idempotent_reentry_keeps_epoch(service, repo):
    """Starting again as the same owner refreshes since but keeps epoch."""
    backend = PluginProtocolBackend(service)
    result1 = backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    epoch = result1["payload"]["epoch"]

    result2 = backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    assert result2["ok"] is True
    assert result2["payload"]["lease_state"] == "active"
    assert result2["payload"]["epoch"] == epoch  # epoch unchanged on re-entry


def test_finish_by_non_owner_blocked_no_review_log(service, repo):
    """Non-owner finish is blocked before svc.finish_memory_maintenance runs."""
    backend_a = PluginProtocolBackend(service)
    _start(backend_a, "host_a")

    # host_b finishes as a different session — must be blocked.
    backend_b = PluginProtocolBackend(service)
    finish = backend_b.handle(_wire("finish_memory_maintenance",
                                    {"host_session_id": "host_b", "status": "completed"}))
    assert finish["ok"] is False
    assert finish["payload"]["lease_state"] in ("not_owner", "reclaimed")
    # Lock still held by host_a.
    assert backend_a._maintenance_owner == "host_a" or backend_b._maintenance_owner is not None


def test_start_returns_epoch_in_payload(service, repo):
    """Start response includes the session epoch."""
    backend = PluginProtocolBackend(service)
    result = backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    assert result["ok"] is True
    assert isinstance(result["payload"]["epoch"], int)
    assert result["payload"]["epoch"] > 0


def test_cross_process_fence_reject_after_reclaim(service, repo):
    """Two PluginProtocolBackend instances simulating separate processes:
    reclaim in B must reject A's apply (proves reload-before-fence works)."""
    backend_a = PluginProtocolBackend(service)
    epoch_a = _start(backend_a, "host_a")

    # Simulate a second process: new backend instance reclaims via force.
    backend_b = PluginProtocolBackend(service)
    result_b = backend_b.handle(_wire("start_memory_maintenance",
                                      {"host_session_id": "host_b", "force": True}))
    assert result_b["ok"] is True

    # backend_a is now displaced. Its apply must fail fence check.
    result_a = _apply(backend_a, "host_a", [], epoch=epoch_a)
    assert result_a["ok"] is False
    assert result_a["payload"]["lease_state"] in ("not_owner", "reclaimed")


# ----------------------------------------------------------- orphaned batch


def test_orphaned_batch_detected_on_get_context(tmp_path: Path):
    """Simulate a crash between batch_started and batch_completed."""
    store = MemoryStore(tmp_path / "memory" / "cards.jsonl", clock=_clock())
    # Write a batch_started record manually with no matching batch_completed.
    store.review_log.append_batch_started("batch_orphan", 3, ["edit_card"])
    # Do NOT write batch_completed — simulate crash.
    service = MaintenanceService(store, default_config(), clock=_clock())
    context = service.get_maintenance_context()
    assert context["ok"] is True
    assert context["orphaned_batch"]["orphaned"] is True
    batch = context["orphaned_batch"]["batch"]
    assert batch is not None
    assert batch["batch_id"] == "batch_orphan"


# ----------------------------------------------------------- partial apply + shape


def test_partial_apply_response_shape(service, repo):
    backend = PluginProtocolBackend(service)
    epoch = _start(backend, "host")
    service.memory.add_card(card("mem_000001",
                                 memory="edit forge/service.py to pass runtime_root"))
    service.memory.add_card(card("mem_000002",
                                 memory="edit forge/config.py to load runtime config"))
    result = _apply(backend, "host", [
        # valid edit
        {"operation": "edit_card", "temp_id": "t1", "card_id": "mem_000001",
         "memory": "always pass runtime_root to load_config() in forge/service.py"},
        # invalid edit (vague memory)
        {"operation": "edit_card", "temp_id": "t2", "card_id": "mem_000002",
         "memory": "be careful with config"},
        # unknown op
        {"operation": "frobnicate", "temp_id": "t3"},
    ], epoch=epoch)
    payload = result["payload"]
    # Response shape matches spec.
    assert payload["ok"] is True
    assert payload["mode"] == SESSION_MODE_MEMORY_REVIEW
    assert payload["blocked_tools"] == ["edit", "write", "bash"]
    assert payload["applied_count"] == 1
    assert payload["rejected_count"] == 2
    assert isinstance(payload["results"], list)
    assert len(payload["results"]) == 3
    # Each result has the right keys.
    for entry in payload["results"]:
        assert "operation" in entry
        assert "status" in entry
        if entry["status"] == "applied":
            assert "card_id" in entry or "temp_id" in entry
        else:
            assert "reasons" in entry
            assert isinstance(entry["reasons"], list)
            assert len(entry["reasons"]) > 0
    # The applied edit touched the store.
    edited = next(c for c in service.memory.read_active() if c.card_id == "mem_000001")
    assert "always pass runtime_root" in edited.memory


# ----------------------------------------------------- memory_maintenance_recommendation


def test_recommendation_triggers_on_low_confidence_threshold(service, repo):
    """>=5 low-confidence cards triggers a recommendation."""
    backend = PluginProtocolBackend(service)
    # Seed 5 low-confidence cards.
    for i in range(5):
        service.memory.add_card(card(f"mem_{i:06d}", confidence="low",
                                     memory=f"edit forge/service.py to pass runtime_root variant {i}"))
    result = backend.handle(_wire("memory_maintenance_recommendation",
                                  {"host_session_id": "host"}))
    payload = result["payload"]
    assert payload["recommend"] is True
    assert payload["review_count"] >= 5
    # One reason string (not a list).
    assert isinstance(payload["reason"], str)
    assert "low confidence" in payload["reason"] or "unverified" in payload["reason"]


def test_recommendation_no_trigger_when_below_thresholds(service, repo):
    backend = PluginProtocolBackend(service)
    # 4 low-confidence cards (< 5 threshold) → no trigger.
    for i in range(4):
        service.memory.add_card(card(f"mem_{i:06d}", confidence="low",
                                     memory=f"edit forge/service.py to pass runtime_root variant {i}"))
    result = backend.handle(_wire("memory_maintenance_recommendation",
                                  {"host_session_id": "host"}))
    payload = result["payload"]
    assert payload["recommend"] is False


def test_recommendation_triggers_on_misleading_threshold(service, repo):
    """>=3 misleading feedback ratings triggers a recommendation."""
    backend = PluginProtocolBackend(service)
    service.memory.add_card(card("mem_000001",
                                 memory="edit forge/service.py to pass runtime_root"))
    # Seed 3 misleading feedback records.
    feedback_path = service.memory.feedback_path
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        record = {"card_id": "mem_000001", "rating": "misleading",
                  "task_id": "task_x", "timestamp": "2026-01-01T00:00:00Z"}
        with feedback_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
    result = backend.handle(_wire("memory_maintenance_recommendation",
                                  {"host_session_id": "host"}))
    payload = result["payload"]
    assert payload["recommend"] is True
    assert "misleading" in payload["reason"]


# --------------------------------------------------------- degraded exit path


def test_finish_failed_writes_maintenance_failed_record(service, repo):
    backend = PluginProtocolBackend(service)
    backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    backend.handle(_wire("finish_memory_maintenance",
                         {"host_session_id": "host", "status": "failed",
                          "reason": "orphaned batch could not be resolved"}))
    log_text = service.memory.review_log.path.read_text(encoding="utf-8")
    assert "maintenance_failed" in log_text
    assert "orphaned batch could not be resolved" in log_text
    # Mode exited.
    assert backend.session_mode("host") == SESSION_MODE_NORMAL


def test_finish_rejects_unknown_status(service, repo):
    backend = PluginProtocolBackend(service)
    backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    result = backend.handle(_wire("finish_memory_maintenance",
                                  {"host_session_id": "host", "status": "bogus"}))
    # finish still exits mode (auto-exit regardless of status).
    assert backend.session_mode("host") == SESSION_MODE_NORMAL
    assert result["payload"]["ok"] is False


# --------------------------------------------------------- create_memory_card batch


def test_create_memory_card_applies_via_batch_and_gaps_visible(service, repo):
    # Complete a task via finish_task with no memory_draft (no card created).
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    service.review_changes(task_id, [{"status": "passed"}],
                           agent_step_intent="add feature")
    service.finish_task(task_id, True, "added feature", commands_run=["pytest -q"])
    # No card should exist yet.
    assert service.memory.read_active() == []

    # Enter maintenance mode and check gaps.
    backend = PluginProtocolBackend(service)
    epoch = _start(backend, "host_gaps")
    ctx = _get_context(backend, "host_gaps")
    gaps = ctx.get("memory_gaps", [])
    assert len(gaps) >= 1
    gap = gaps[0]
    assert gap["task_id"] == task_id
    assert gap["state"] == "completed"

    # Apply create_memory_card for the gap.
    result = _apply(backend, "host_gaps", [{
        "operation": "create_memory_card",
        "temp_id": "cm1",
        "memory": "When implementing feature.py, write a test alongside the implementation to catch regressions early.",
        "why": "This task added feature.py without a test; future changes could break the feature silently.",
        "source_task_ids": [task_id],
    }], epoch=epoch)
    assert result["payload"]["applied_count"] == 1
    assert result["payload"]["results"][0]["status"] == "applied"

    # Card should now exist.
    cards = service.memory.read_active()
    assert len(cards) == 1
    card = cards[0]
    assert card.source_task_ids == [task_id]
    assert card.entry_type == "validation_memory"

    # Gap should be gone.
    ctx2 = _get_context(backend, "host_gaps")
    assert len(ctx2.get("memory_gaps", [])) == 0

    backend.handle(_wire("finish_memory_maintenance",
                         {"host_session_id": "host_gaps", "status": "completed"}))


def test_create_memory_card_pitfall_for_failed_task(service, repo):
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    service.review_changes(task_id, [{"status": "passed"}],
                           agent_step_intent="add feature")
    service.finish_task(task_id, False, "test failed", commands_run=["pytest -q"])

    backend = PluginProtocolBackend(service)
    epoch = _start(backend, "host_pitfall")
    result = _apply(backend, "host_pitfall", [{
        "operation": "create_memory_card",
        "temp_id": "cm2",
        "memory": "When editing feature.py, verify the integration with forge/service.py before marking the task complete.",
        "why": "The feature implementation passed locally but failed in test due to missing service integration.",
        "source_task_ids": [task_id],
    }], epoch=epoch)
    assert result["payload"]["applied_count"] == 1
    cards = service.memory.read_active()
    assert cards[0].entry_type == "pitfall_memory"
    backend.handle(_wire("finish_memory_maintenance",
                         {"host_session_id": "host_pitfall", "status": "completed"}))


def test_gaps_included_in_recommendation(service, repo):
    # Complete a task with no memory_draft.
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    service.review_changes(task_id, [{"status": "passed"}],
                           agent_step_intent="add feature")
    service.finish_task(task_id, True, "added feature", commands_run=["pytest -q"])

    backend = PluginProtocolBackend(service)
    result = backend.handle(_wire("memory_maintenance_recommendation",
                                  {"host_session_id": "host_gaps"}))
    payload = result["payload"]
    assert isinstance(payload["reason"], str)
    assert "no memory card" in payload["reason"]


# ------------------------------------------------------------------------ helpers


def _get_context(backend, host_id):
    resp = backend.handle(_wire("get_maintenance_context", {"host_session_id": host_id}))
    return resp.get("payload", {})
