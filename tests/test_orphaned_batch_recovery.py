"""Crash-during-batch recovery tests for orphaned batch detection.

Simulates a process that dies between ``batch_started`` and
``batch_completed`` and verifies that:
  * the happy path (started + completed) is NOT flagged orphaned
  * a crashed batch IS detected by a fresh MaintenanceService (restart)
  * the surrounding maintenance context stays sane
  * ``finish_memory_maintenance(status="failed")`` records the failure
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from forge.config import default_config
from forge.memory.cards import AppliesWhen, MemoryCard
from forge.memory.maintenance_service import MaintenanceService
from forge.memory.store import MemoryStore


def _clock() -> Callable[[], float]:
    counter = iter(range(1000))
    return lambda: float(next(counter))


def card(card_id: str = "", **values) -> MemoryCard:
    defaults = {
        "card_id": card_id,
        "memory": f"edit forge/service.py to pass runtime_root for {card_id or 'new'}",
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


def _store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory" / "cards.jsonl", clock=_clock())


def test_happy_path_batch_is_not_orphaned(tmp_path: Path):
    store = _store(tmp_path)
    store.add_card(card("mem_000001"))
    svc = MaintenanceService(store, default_config(), clock=_clock())

    result = svc.apply_memory_review_batch([
        {"operation": "edit_card", "temp_id": "t1", "card_id": "mem_000001",
         "memory": "always pass runtime_root to load_config() in forge/service.py"},
    ])
    assert result["ok"] is True
    assert result["applied_count"] == 1
    assert result["rejected_count"] == 0

    orphaned, batch = store.review_log.last_batch_orphaned()
    assert orphaned is False
    assert batch is None


def test_crash_mid_batch_is_detected_after_restart(tmp_path: Path):
    store = _store(tmp_path)
    store.add_card(card("mem_000001"))
    svc = MaintenanceService(store, default_config(), clock=_clock())

    # Happy-path batch first: started + completed.
    svc.apply_memory_review_batch([
        {"operation": "edit_card", "temp_id": "t1", "card_id": "mem_000001",
         "memory": "always pass runtime_root to load_config() in forge/service.py"},
    ])
    assert store.review_log.last_batch_orphaned() == (False, None)

    # Simulate a crash: a second batch is started but the process dies
    # before batch_completed is written.
    store.review_log.append_batch_started("batch_crash", 1, ["edit_card"])

    # A fresh service instance simulates a restart pointing at the same store.
    restarted = MaintenanceService(store, default_config(), clock=_clock())
    context = restarted.get_maintenance_context()

    assert context["ok"] is True
    orphan = context["orphaned_batch"]
    assert orphan["orphaned"] is True
    assert orphan["batch"] is not None
    assert orphan["batch"]["batch_id"] == "batch_crash"

    # The rest of the context remains sane.
    assert isinstance(context["active_cards"], list)
    assert len(context["active_cards"]) == 1
    assert context["active_cards"][0]["card_id"] == "mem_000001"
    assert isinstance(context["archived_cards"], list)
    assert context["archived_cards"] == []
    rec = context["recommendation"]
    assert "recommend" in rec and "reason" in rec and "review_count" in rec
    assert rec["recommend"] is False  # one medium card crosses no threshold


def test_finish_failed_records_failure_after_orphan(tmp_path: Path):
    store = _store(tmp_path)
    store.add_card(card("mem_000001"))
    svc = MaintenanceService(store, default_config(), clock=_clock())

    # Crash mid-batch.
    store.review_log.append_batch_started("batch_crash", 1, ["edit_card"])

    restarted = MaintenanceService(store, default_config(), clock=_clock())
    context = restarted.get_maintenance_context()
    assert context["orphaned_batch"]["orphaned"] is True

    # Resolve by failing the maintenance session with a reason referencing the orphan.
    reason = "orphaned batch batch_crash could not be completed; aborting maintenance"
    outcome = restarted.finish_memory_maintenance("failed", reason=reason)
    assert outcome["ok"] is True
    assert outcome["status"] == "failed"
    assert outcome["reason"] == reason

    log_text = store.review_log.path.read_text(encoding="utf-8")
    assert "maintenance_failed" in log_text
    assert reason in log_text

    # The orphan is now resolved — a fresh context must NOT report it.
    cleared = restarted.get_maintenance_context()
    assert cleared["orphaned_batch"]["orphaned"] is False
