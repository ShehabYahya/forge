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
    assert len(HIDDEN_OPERATIONS) == 9


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
    assert "forge_finish_task" in result["payload"]["allowed_tools"]
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
    backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    # Seed a card to edit.
    service.memory.add_card(card("mem_000001",
                                 memory="edit forge/service.py to pass runtime_root"))
    result = backend.handle(_wire("apply_memory_review_batch", {
        "host_session_id": "host",
        "operations": [
            {"operation": "edit_card", "temp_id": "t1", "card_id": "mem_000001",
             "memory": "always pass runtime_root to load_config() in forge/service.py"},
        ],
    }))
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
    backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    service.memory.add_card(card("mem_000001",
                                 memory="edit forge/service.py to pass runtime_root"))
    service.memory.add_card(card("mem_000002",
                                 memory="edit forge/config.py to load runtime config"))
    result = backend.handle(_wire("apply_memory_review_batch", {
        "host_session_id": "host",
        "operations": [
            # valid edit
            {"operation": "edit_card", "temp_id": "t1", "card_id": "mem_000001",
             "memory": "always pass runtime_root to load_config() in forge/service.py"},
            # invalid edit (vague memory)
            {"operation": "edit_card", "temp_id": "t2", "card_id": "mem_000002",
             "memory": "be careful with config"},
            # unknown op
            {"operation": "frobnicate", "temp_id": "t3"},
        ],
    }))
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
