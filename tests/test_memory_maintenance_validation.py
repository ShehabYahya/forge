from __future__ import annotations

"""Per-operation validation tests for /review-memory batch apply.

Covers:
  * vague cards rejected per-op with reasons (anti-vague via T2)
  * valid siblings still apply (partial apply)
  * pattern <2 sources rejected
  * pattern without concrete anchor rejected
  * pattern duplicate (normalized text matches active) rejected
  * pattern why without recurrence word/number rejected
  * high-rated archive blocked (agent_score >= 0.7 and n >= 5)
  * restore with weak reason rejected (must reference misread/mistake/wrong/error)
"""

import json
from pathlib import Path
from typing import Callable

import pytest

from forge.config import default_config
from forge.memory.cards import AppliesWhen, MemoryCard
from forge.memory.maintenance_schema import (
    ArchiveCardOp,
    CreateMemoryCardOp,
    CreatePatternCardOp,
    EditCardOp,
    RestoreCardOp,
)
from forge.memory.maintenance_service import MaintenanceService
from forge.memory.maintenance_validator import (
    validate_archive,
    validate_create_memory,
    validate_create_pattern,
    validate_edit,
    validate_restore,
)
from forge.memory.store import MemoryStore
from forge.task_state import TaskSnapshot


def _clock() -> Callable[[], float]:
    counter = iter(range(1000))
    return lambda: float(next(counter))


def make_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory" / "cards.jsonl", clock=_clock())


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


# ----------------------------------------------------------------- edit / vague


def test_edit_vague_memory_rejected_with_reason(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    cfg = default_config()
    op = EditCardOp(temp_id="t1", card_id="mem_000001",
                    memory="be careful when editing the config module")
    reasons = validate_edit(op, store, cfg)
    assert reasons, "vague memory must be rejected"
    assert any("generic" in r.lower() for r in reasons)


def test_edit_too_short_memory_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001"))
    cfg = default_config()
    op = EditCardOp(temp_id="t1", card_id="mem_000001", memory="too short")
    reasons = validate_edit(op, store, cfg)
    assert any("at least" in r for r in reasons)


def test_edit_missing_card_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    cfg = default_config()
    op = EditCardOp(temp_id="t1", card_id="mem_999999", memory="x" * 50)
    reasons = validate_edit(op, store, cfg)
    assert any("not found" in r for r in reasons)


def test_edit_no_changes_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001"))
    cfg = default_config()
    op = EditCardOp(temp_id="t1", card_id="mem_000001")
    reasons = validate_edit(op, store, cfg)
    assert any("at least one field" in r for r in reasons)


def test_valid_siblings_apply_even_when_one_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    store.add_card(card("mem_000002", memory="edit forge/config.py to load runtime config"))
    cfg = default_config()
    service = MaintenanceService(store, cfg, clock=_clock())
    operations = [
        {
            "operation": "edit_card",
            "temp_id": "good",
            "card_id": "mem_000001",
            "memory": "always pass runtime_root to load_config() in forge/service.py",
        },
        {
            "operation": "edit_card",
            "temp_id": "bad",
            "card_id": "mem_000002",
            "memory": "be careful with config",
        },
    ]
    result = service.apply_memory_review_batch(operations)
    assert result["ok"] is True
    assert result["applied_count"] == 1
    assert result["rejected_count"] == 1
    statuses = {r["temp_id"]: r["status"] for r in result["results"]}
    assert statuses["good"] == "applied"
    assert statuses["bad"] == "rejected"


# --------------------------------------------------------------- pattern rules


def _seed_tasks_and_telemetry(tmp_path: Path, task_ids: list[str]) -> None:
    """Write minimal tasks.jsonl (terminal) and telemetry.jsonl records."""
    tasks_path = tmp_path / "tasks.jsonl"
    for tid in task_ids:
        snap = TaskSnapshot(
            task_id=tid, state="completed", task_text=f"task {tid}",
            repo_root="/repo", created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        with tasks_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(snap.to_dict()) + "\n")
    telemetry_path = tmp_path / "telemetry.jsonl"
    for tid in task_ids:
        record = {"schema_version": 1, "event": "task_finished",
                  "task_id": tid, "timestamp": "2026-01-01T00:00:00Z",
                  "success": True}
        with telemetry_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")


class _FakeTaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._tasks: dict[str, TaskSnapshot] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                snap = TaskSnapshot.from_dict(json.loads(line))
                self._tasks[snap.task_id] = snap

    def all(self) -> list[TaskSnapshot]:
        return list(self._tasks.values())


def _make_service(tmp_path: Path, task_ids: list[str]) -> MaintenanceService:
    _seed_tasks_and_telemetry(tmp_path, task_ids)
    store = make_store(tmp_path)
    cfg = default_config()
    return MaintenanceService(
        store, cfg,
        task_store=_FakeTaskStore(tmp_path / "tasks.jsonl"),
        telemetry_path=tmp_path / "telemetry.jsonl",
        clock=_clock(),
    )


VALID_PATTERN_MEMORY = (
    "Across multiple refactors of forge/service.py, pass runtime_root to "
    "load_config() so the home directory is not hardcoded for tests."
)
VALID_PATTERN_WHY = (
    "This recurred across 3 separate tasks editing forge/service.py; each "
    "regression missed the override path."
)


def test_pattern_with_fewer_than_two_sources_rejected(tmp_path: Path) -> None:
    service = _make_service(tmp_path, ["task_a"])
    op = CreatePatternCardOp(
        temp_id="new_1", memory=VALID_PATTERN_MEMORY, why=VALID_PATTERN_WHY,
        source_task_ids=["task_a"],
    )
    reasons = validate_create_pattern(
        op, service.store, service.config,
        tasks_by_id=service._tasks_by_id(),
        telemetry_task_ids=service._telemetry_task_ids(),
    )
    assert any(">=2 source tasks" in r for r in reasons)


def test_pattern_without_concrete_anchor_rejected(tmp_path: Path) -> None:
    service = _make_service(tmp_path, ["task_a", "task_b"])
    op = CreatePatternCardOp(
        temp_id="new_1",
        memory="Always be careful when making changes across the codebase.",
        why=VALID_PATTERN_WHY,
        source_task_ids=["task_a", "task_b"],
    )
    reasons = validate_create_pattern(
        op, service.store, service.config,
        tasks_by_id=service._tasks_by_id(),
        telemetry_task_ids=service._telemetry_task_ids(),
    )
    assert any("concrete anchor" in r for r in reasons)


def test_pattern_duplicate_of_active_card_rejected(tmp_path: Path) -> None:
    service = _make_service(tmp_path, ["task_a", "task_b"])
    # Seed an active card whose normalized memory matches the pattern memory.
    service.store.add_card(card("mem_000001", memory=VALID_PATTERN_MEMORY))
    op = CreatePatternCardOp(
        temp_id="new_1", memory=VALID_PATTERN_MEMORY, why=VALID_PATTERN_WHY,
        source_task_ids=["task_a", "task_b"],
    )
    reasons = validate_create_pattern(
        op, service.store, service.config,
        tasks_by_id=service._tasks_by_id(),
        telemetry_task_ids=service._telemetry_task_ids(),
    )
    assert any("duplicate" in r.lower() for r in reasons)


def test_pattern_why_without_recurrence_rejected(tmp_path: Path) -> None:
    service = _make_service(tmp_path, ["task_a", "task_b"])
    op = CreatePatternCardOp(
        temp_id="new_1", memory=VALID_PATTERN_MEMORY,
        why="This is a useful lesson about forge/service.py.",
        source_task_ids=["task_a", "task_b"],
    )
    reasons = validate_create_pattern(
        op, service.store, service.config,
        tasks_by_id=service._tasks_by_id(),
        telemetry_task_ids=service._telemetry_task_ids(),
    )
    assert any("recurrence" in r.lower() for r in reasons)


def test_pattern_with_unfinished_source_rejected(tmp_path: Path) -> None:
    # Seed one task as active (non-terminal).
    tasks_path = tmp_path / "tasks.jsonl"
    snap_active = TaskSnapshot(
        task_id="task_active", state="active", task_text="t",
        repo_root="/repo", created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    snap_done = TaskSnapshot(
        task_id="task_done", state="completed", task_text="t",
        repo_root="/repo", created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    with tasks_path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(snap_active.to_dict()) + "\n")
        stream.write(json.dumps(snap_done.to_dict()) + "\n")
    telemetry_path = tmp_path / "telemetry.jsonl"
    for tid in ("task_active", "task_done"):
        record = {"schema_version": 1, "event": "task_finished",
                  "task_id": tid, "timestamp": "2026-01-01T00:00:00Z",
                  "success": True}
        with telemetry_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
    store = make_store(tmp_path)
    service = MaintenanceService(
        store, default_config(),
        task_store=_FakeTaskStore(tasks_path),
        telemetry_path=telemetry_path,
        clock=_clock(),
    )
    op = CreatePatternCardOp(
        temp_id="new_1", memory=VALID_PATTERN_MEMORY, why=VALID_PATTERN_WHY,
        source_task_ids=["task_active", "task_done"],
    )
    reasons = validate_create_pattern(
        op, service.store, service.config,
        tasks_by_id=service._tasks_by_id(),
        telemetry_task_ids=service._telemetry_task_ids(),
    )
    assert any("terminal state" in r for r in reasons)


def test_pattern_with_no_telemetry_source_rejected(tmp_path: Path) -> None:
    # Two terminal tasks but only one has telemetry.
    tasks_path = tmp_path / "tasks.jsonl"
    for tid in ("task_a", "task_b"):
        snap = TaskSnapshot(
            task_id=tid, state="completed", task_text="t",
            repo_root="/repo", created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        with tasks_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(snap.to_dict()) + "\n")
    telemetry_path = tmp_path / "telemetry.jsonl"
    record = {"schema_version": 1, "event": "task_finished",
              "task_id": "task_a", "timestamp": "2026-01-01T00:00:00Z",
              "success": True}
    with telemetry_path.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
    store = make_store(tmp_path)
    service = MaintenanceService(
        store, default_config(),
        task_store=_FakeTaskStore(tasks_path),
        telemetry_path=telemetry_path,
        clock=_clock(),
    )
    op = CreatePatternCardOp(
        temp_id="new_1", memory=VALID_PATTERN_MEMORY, why=VALID_PATTERN_WHY,
        source_task_ids=["task_a", "task_b"],
    )
    reasons = validate_create_pattern(
        op, service.store, service.config,
        tasks_by_id=service._tasks_by_id(),
        telemetry_task_ids=service._telemetry_task_ids(),
    )
    assert any("no telemetry" in r for r in reasons)


def test_valid_pattern_applies(tmp_path: Path) -> None:
    service = _make_service(tmp_path, ["task_a", "task_b"])
    result = service.apply_memory_review_batch([
        {
            "operation": "create_pattern_card",
            "temp_id": "new_1",
            "memory": VALID_PATTERN_MEMORY,
            "why": VALID_PATTERN_WHY,
            "source_task_ids": ["task_a", "task_b"],
            "task_types": ["refactor"],
            "files": ["forge/service.py"],
            "modules": ["forge"],
        },
    ])
    assert result["applied_count"] == 1
    assert result["rejected_count"] == 0
    res = result["results"][0]
    assert res["status"] == "applied"
    assert res["card_id"].startswith("mem_")
    # Card was actually written to the store.
    new_card = next(c for c in service.store.read_active() if c.card_id == res["card_id"])
    assert new_card.entry_type == "cross_task_pattern"
    assert new_card.source_task_ids == ["task_a", "task_b"]
    context = service.get_maintenance_context()
    assert {event["task_id"] for event in context["telemetry"]} == {"task_a", "task_b"}


# ------------------------------------------------------------- archive rules


def test_high_rated_archive_blocked(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    # Seed feedback: enough helpful ratings to push agent_score >= 0.7 with n >= 5.
    feedback_path = store.feedback_path
    feedback_path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(6):
        record = {"card_id": "mem_000001", "rating": "helpful",
                  "task_id": "task_x", "timestamp": "2026-01-01T00:00:00Z"}
        with feedback_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
    cfg = default_config()
    feedback_aggregate = store.read_feedback_aggregate()
    bucket = feedback_aggregate["mem_000001"]
    assert bucket["n"] >= 5
    op = ArchiveCardOp(temp_id="t1", card_id="mem_000001",
                       reason="contradicted by telemetry in task_x")
    reasons = validate_archive(op, store, cfg, feedback_aggregate)
    assert any("high-rated" in r for r in reasons), reasons


def test_low_observed_card_archive_allowed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    # No feedback → agent_score = 0.5, n = 0 → not high-rated.
    cfg = default_config()
    feedback_aggregate = store.read_feedback_aggregate()
    op = ArchiveCardOp(temp_id="t1", card_id="mem_000001",
                       reason="contradicted by telemetry in task_x")
    reasons = validate_archive(op, store, cfg, feedback_aggregate)
    assert reasons == [], reasons


def test_archive_missing_reason_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001"))
    cfg = default_config()
    op = ArchiveCardOp(temp_id="t1", card_id="mem_000001", reason="")
    reasons = validate_archive(op, store, cfg, store.read_feedback_aggregate())
    assert any("reason" in r.lower() for r in reasons)


def test_archive_applies_via_batch(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    service = MaintenanceService(store, default_config(), clock=_clock())
    result = service.apply_memory_review_batch([
        {"operation": "archive_card", "temp_id": "a1",
         "card_id": "mem_000001", "reason": "contradicted by telemetry in task_x"},
    ])
    assert result["applied_count"] == 1
    archived = store.read_archived()
    assert any(c.card_id == "mem_000001" for c in archived)
    assert store.read_active() == []


# --------------------------------------------------------------- restore rules


def test_restore_weak_reason_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    # Seed an archived card.
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    store.archive_card("mem_000001", "old reason")
    cfg = default_config()
    op = RestoreCardOp(temp_id="r1", card_id="mem_000001",
                       reason="I want this card back in the active set.")
    reasons = validate_restore(op, store, cfg)
    assert any("why the archive was wrong" in r for r in reasons)


def test_restore_strong_reason_accepted(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    store.archive_card("mem_000001", "old reason")
    cfg = default_config()
    op = RestoreCardOp(temp_id="r1", card_id="mem_000001",
                       reason="telemetry evidence was misread; card was archived by mistake")
    reasons = validate_restore(op, store, cfg)
    assert reasons == [], reasons


def test_restore_missing_card_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    cfg = default_config()
    op = RestoreCardOp(temp_id="r1", card_id="mem_999999",
                       reason="archived by mistake")
    reasons = validate_restore(op, store, cfg)
    assert any("not found" in r for r in reasons)


# --------------------------------------------------------------- merge / compact


def test_merge_requires_two_cards(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    service = MaintenanceService(store, default_config(), clock=_clock())
    result = service.apply_memory_review_batch([
        {
            "operation": "merge_cards", "temp_id": "m1",
            "card_ids": ["mem_000001"],
            "memory": "merged memory about forge/service.py runtime_root",
            "why": "two cards said the same thing about forge/service.py",
        },
    ])
    assert result["rejected_count"] == 1
    assert any("at least 2" in r for r in result["results"][0]["reasons"])


def test_merge_applies_and_archives_originals(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    store.add_card(card("mem_000002", memory="always pass runtime_root to load_config in forge/config.py"))
    service = MaintenanceService(store, default_config(), clock=_clock())
    result = service.apply_memory_review_batch([
        {
            "operation": "merge_cards", "temp_id": "m1",
            "card_ids": ["mem_000001", "mem_000002"],
            "memory": "merged: pass runtime_root to load_config() in forge/service.py and forge/config.py",
            "why": "two cards covered the same runtime_root override pattern",
            "avoid": "hardcoding the home directory in either module",
        },
    ])
    assert result["applied_count"] == 1
    res = result["results"][0]
    assert res["status"] == "applied"
    new_id = res["card_id"]
    archived_ids = {c.card_id for c in store.read_archived()}
    assert "mem_000001" in archived_ids
    assert "mem_000002" in archived_ids
    new_card = next(c for c in store.read_active() if c.card_id == new_id)
    assert new_card.supersedes == ["mem_000001", "mem_000002"]


def test_compact_applies_with_kind_compact(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory="edit forge/service.py to pass runtime_root"))
    store.add_card(card("mem_000002", memory="edit forge/service.py to pass runtime_root via load_config"))
    service = MaintenanceService(store, default_config(), clock=_clock())
    result = service.apply_memory_review_batch([
        {
            "operation": "compact_cards", "temp_id": "c1",
            "card_ids": ["mem_000001", "mem_000002"],
            "memory": "compacted: pass runtime_root to load_config() in forge/service.py",
            "why": "two redundant cards about the same forge/service.py override",
        },
    ])
    assert result["applied_count"] == 1
    assert result["results"][0]["status"] == "applied"


# --------------------------------------------------------------- create_memory_card


VALID_MEMORY_TEXT = "When editing forge/service.py, pass runtime_root to load_config() to avoid hardcoding the home directory."

VALID_MEMORY_WHY = "This regression recurred across multiple tasks touching forge/service.py without updating the config path."


def test_create_memory_valid_single_source_applied(tmp_path: Path) -> None:
    _seed_tasks_and_telemetry(tmp_path, ["task_a"])
    store = make_store(tmp_path)
    cfg = default_config()
    from forge.memory.maintenance_validator import validate_create_memory
    from forge.memory.maintenance_schema import CreateMemoryCardOp
    tasks_by_id = {snap.task_id: snap for snap in _FakeTaskStore(tmp_path / "tasks.jsonl").all()}
    telemetry_task_ids = {"task_a"}
    op = CreateMemoryCardOp(
        temp_id="new_1", memory=VALID_MEMORY_TEXT, why=VALID_MEMORY_WHY,
        source_task_ids=["task_a"],
    )
    reasons = validate_create_memory(
        op, store, cfg,
        tasks_by_id=tasks_by_id,
        telemetry_task_ids=telemetry_task_ids,
    )
    assert reasons == [], reasons


def test_create_memory_zero_sources_rejected(tmp_path: Path) -> None:
    _seed_tasks_and_telemetry(tmp_path, ["task_a"])
    store = make_store(tmp_path)
    cfg = default_config()
    from forge.memory.maintenance_validator import validate_create_memory
    from forge.memory.maintenance_schema import CreateMemoryCardOp
    tasks_by_id = {snap.task_id: snap for snap in _FakeTaskStore(tmp_path / "tasks.jsonl").all()}
    telemetry_task_ids = {"task_a"}
    op = CreateMemoryCardOp(
        temp_id="new_1", memory=VALID_MEMORY_TEXT, why=VALID_MEMORY_WHY,
        source_task_ids=[],
    )
    reasons = validate_create_memory(
        op, store, cfg,
        tasks_by_id=tasks_by_id,
        telemetry_task_ids=telemetry_task_ids,
    )
    assert any("exactly 1" in r for r in reasons)


def test_create_memory_two_sources_rejected(tmp_path: Path) -> None:
    _seed_tasks_and_telemetry(tmp_path, ["task_a", "task_b"])
    store = make_store(tmp_path)
    cfg = default_config()
    from forge.memory.maintenance_validator import validate_create_memory
    from forge.memory.maintenance_schema import CreateMemoryCardOp
    tasks_by_id = {snap.task_id: snap for snap in _FakeTaskStore(tmp_path / "tasks.jsonl").all()}
    telemetry_task_ids = {"task_a", "task_b"}
    op = CreateMemoryCardOp(
        temp_id="new_1", memory=VALID_MEMORY_TEXT, why=VALID_MEMORY_WHY,
        source_task_ids=["task_a", "task_b"],
    )
    reasons = validate_create_memory(
        op, store, cfg,
        tasks_by_id=tasks_by_id,
        telemetry_task_ids=telemetry_task_ids,
    )
    assert any("exactly 1" in r for r in reasons)


def test_create_memory_non_terminal_task_rejected(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.jsonl"
    snap = TaskSnapshot(
        task_id="task_active", state="active", task_text="active task",
        repo_root="/repo", created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    with tasks_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(snap.to_dict()) + "\n")
    telemetry_path = tmp_path / "telemetry.jsonl"
    with telemetry_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"schema_version": 1, "event": "task_started", "task_id": "task_active", "timestamp": "2026-01-01T00:00:00Z"}) + "\n")
    store = make_store(tmp_path)
    cfg = default_config()
    from forge.memory.maintenance_validator import validate_create_memory
    from forge.memory.maintenance_schema import CreateMemoryCardOp
    tasks_by_id = {snap.task_id: snap for snap in _FakeTaskStore(tasks_path).all()}
    telemetry_task_ids = {"task_active"}
    op = CreateMemoryCardOp(
        temp_id="new_1", memory=VALID_MEMORY_TEXT, why=VALID_MEMORY_WHY,
        source_task_ids=["task_active"],
    )
    reasons = validate_create_memory(
        op, store, cfg,
        tasks_by_id=tasks_by_id,
        telemetry_task_ids=telemetry_task_ids,
    )
    assert any("terminal" in r for r in reasons)


def test_create_memory_without_concrete_anchor_rejected(tmp_path: Path) -> None:
    _seed_tasks_and_telemetry(tmp_path, ["task_a"])
    store = make_store(tmp_path)
    cfg = default_config()
    from forge.memory.maintenance_validator import validate_create_memory
    from forge.memory.maintenance_schema import CreateMemoryCardOp
    tasks_by_id = {snap.task_id: snap for snap in _FakeTaskStore(tmp_path / "tasks.jsonl").all()}
    telemetry_task_ids = {"task_a"}
    op = CreateMemoryCardOp(
        temp_id="new_1",
        memory="Always be careful when making changes across the codebase.",
        why=VALID_MEMORY_WHY,
        source_task_ids=["task_a"],
    )
    reasons = validate_create_memory(
        op, store, cfg,
        tasks_by_id=tasks_by_id,
        telemetry_task_ids=telemetry_task_ids,
    )
    assert any("concrete anchor" in r for r in reasons)


def test_create_memory_duplicate_rejected(tmp_path: Path) -> None:
    _seed_tasks_and_telemetry(tmp_path, ["task_a"])
    store = make_store(tmp_path)
    store.add_card(card("mem_000001", memory=VALID_MEMORY_TEXT))
    cfg = default_config()
    from forge.memory.maintenance_validator import validate_create_memory
    from forge.memory.maintenance_schema import CreateMemoryCardOp
    tasks_by_id = {snap.task_id: snap for snap in _FakeTaskStore(tmp_path / "tasks.jsonl").all()}
    telemetry_task_ids = {"task_a"}
    op = CreateMemoryCardOp(
        temp_id="new_1", memory=VALID_MEMORY_TEXT, why=VALID_MEMORY_WHY,
        source_task_ids=["task_a"],
    )
    reasons = validate_create_memory(
        op, store, cfg,
        tasks_by_id=tasks_by_id,
        telemetry_task_ids=telemetry_task_ids,
    )
    assert any("duplicates" in r for r in reasons)
