from __future__ import annotations

from pathlib import Path
from typing import Callable
import multiprocessing

import pytest

from forge.memory.cards import AppliesWhen, MemoryCard
from forge.memory.review_log import ReviewLog
from forge.memory.store import MemoryStore


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


def make_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory" / "cards.jsonl", clock=_clock())


def _add_card_process(storage_root: str, card_id: str) -> None:
    MemoryStore(Path(storage_root)).add_card(card(card_id))


# ----------------------------------------------------------------- monotonic ids


def test_next_id_starts_at_mem_000001(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    assert s.next_id() == "mem_000001"


def test_next_id_is_sequentially_monotonic(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    ids = [s.next_id() for _ in range(5)]
    assert ids == ["mem_000001", "mem_000002", "mem_000003",
                   "mem_000004", "mem_000005"]


def test_next_id_is_six_digit_zero_padded(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    assert s.next_id() == "mem_000001"


def test_next_id_persists_across_store_instances(tmp_path: Path) -> None:
    s1 = make_store(tmp_path)
    s1.next_id()
    s1.next_id()
    s2 = make_store(tmp_path)
    assert s2.next_id() == "mem_000003"


def test_next_id_counter_survives_many_sequential_calls(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    for _ in range(100):
        s.next_id()
    assert s.next_id() == "mem_000101"


# ------------------------------------------------------------- active/deleted split


def test_add_card_then_load_returns_it(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    s.add_card(card("mem_000001"))
    loaded, warnings = s.load()
    assert len(loaded) == 1
    assert loaded[0].card_id == "mem_000001"
    assert warnings == []


def test_concurrent_adds_preserve_every_card(tmp_path: Path) -> None:
    storage_root = tmp_path / "memory"
    processes = [
        multiprocessing.Process(
            target=_add_card_process,
            args=(str(storage_root), f"mem_{index:06d}"),
        )
        for index in range(1, 9)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    assert {item.card_id for item in MemoryStore(storage_root).read_active()} == {
        f"mem_{index:06d}" for index in range(1, 9)
    }


def test_archive_moves_card_out_of_active_into_deleted(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    s.add_card(card("mem_000001"))
    archived = s.archive_card("mem_000001", reason="contradicted by telemetry")
    assert archived.card_id == "mem_000001"
    assert s.read_active() == []
    deleted = s.read_archived()
    assert len(deleted) == 1
    assert deleted[0].card_id == "mem_000001"


def test_archive_unknown_card_raises_keyerror(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    with pytest.raises(KeyError):
        s.archive_card("mem_999999", reason="missing")


def test_edit_card_updates_fields_and_persists(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    s.add_card(card("mem_000001", confidence="high"))
    updated = s.edit_card("mem_000001", confidence="low",
                          why="downgraded after telemetry review")
    assert updated.confidence == "low"
    assert updated.why == "downgraded after telemetry review"
    assert s.read_active()[0].confidence == "low"


def test_edit_card_unknown_raises_keyerror(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    with pytest.raises(KeyError):
        s.edit_card("mem_999999", memory="x")


# ------------------------------------------------------- feedback append isolation


def test_feedback_append_does_not_corrupt_active(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    original = card("mem_000001")
    s.add_card(original)
    s.feedback.append_feedback("task_1", "mem_000001", "helpful", "worked well")
    s.feedback.append_feedback("task_2", "mem_000001", "unused")
    active = s.read_active()
    assert len(active) == 1
    assert active[0].card_id == "mem_000001"
    assert active[0].memory == original.memory


def test_read_feedback_aggregate_counts_ratings(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    s.feedback.append_feedback("task_1", "mem_000001", "helpful")
    s.feedback.append_feedback("task_2", "mem_000001", "helpful")
    s.feedback.append_feedback("task_3", "mem_000001", "unused")
    s.feedback.append_feedback("task_4", "mem_000001", "misleading")
    agg = s.read_feedback_aggregate()
    assert agg["mem_000001"]["helpful"] == 2
    assert agg["mem_000001"]["unused"] == 1
    assert agg["mem_000001"]["misleading"] == 1
    assert agg["mem_000001"]["n"] == 4


def test_read_feedback_aggregate_unknown_rating_bucketed(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    s.feedback.append_feedback("task_1", "mem_000001", "bogus_rating")
    agg = s.read_feedback_aggregate()
    assert agg["mem_000001"]["unknown"] == 1
    assert agg["mem_000001"]["n"] == 1


# --------------------------------------------------------------- merge lineage


def test_merge_lineage_supersedes_archives_and_unions_task_ids(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    id1 = s.next_id()
    id2 = s.next_id()
    s.add_card(card(id1, source_task_ids=["t1", "t2"]))
    s.add_card(card(id2, source_task_ids=["t2", "t3"]))
    merged = s.merge_cards(
        [id1, id2],
        card("", memory="merged lesson about forge/service.py",
             source_task_ids=["t3", "t4"]),
        kind="merge",
        reason="compact duplicates",
    )
    assert merged.card_id == "mem_000003"
    assert merged.supersedes == [id1, id2]
    assert set(merged.source_task_ids) == {"t1", "t2", "t3", "t4"}
    assert [c.card_id for c in s.read_active()] == ["mem_000003"]
    deleted = {c.card_id: c for c in s.read_archived()}
    assert deleted[id1].superseded_by == "mem_000003"
    assert deleted[id2].superseded_by == "mem_000003"


def test_merge_keeps_provided_card_id(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    s.add_card(card("mem_000001"))
    merged = s.merge_cards(
        ["mem_000001"],
        card("mem_000099", memory="keep this specific id"),
    )
    assert merged.card_id == "mem_000099"
    assert merged.supersedes == ["mem_000001"]


def test_merge_unknown_source_raises_keyerror(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    with pytest.raises(KeyError):
        s.merge_cards(["mem_999999"], card("", memory="merge lesson here"))


def test_merge_compact_kind_archives_sources(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    id1 = s.next_id()
    id2 = s.next_id()
    s.add_card(card(id1))
    s.add_card(card(id2))
    merged = s.merge_cards(
        [id1, id2],
        card("", memory="compacted lesson about forge/config.py"),
        kind="compact",
    )
    assert merged.card_id == "mem_000003"
    assert len(s.read_active()) == 1
    assert len(s.read_archived()) == 2


# ------------------------------------------------------- restore clears superseded_by


def test_restore_clears_superseded_by(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    id1 = s.next_id()
    id2 = s.next_id()
    s.add_card(card(id1, source_task_ids=["t1"]))
    s.add_card(card(id2, source_task_ids=["t2"]))
    s.merge_cards([id1, id2],
                  card("", memory="merged lesson about forge/service.py"))
    deleted = {c.card_id: c for c in s.read_archived()}
    assert deleted[id1].superseded_by is not None
    restored = s.restore_card(id1, reason="archive was mistaken; telemetry misread")
    assert restored.superseded_by is None
    active_ids = {c.card_id for c in s.read_active()}
    assert id1 in active_ids
    assert id2 not in active_ids


def test_restore_unknown_raises_keyerror(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    with pytest.raises(KeyError):
        s.restore_card("mem_999999", reason="missing")


# ------------------------------------------- deleted-store wrapper round-trip


def test_deleted_wrapper_round_trip_via_read_archived(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    original = card("mem_000001",
                    memory="specific note about forge/config.py loading",
                    why="past issue with home dir override",
                    confidence="high")
    s.add_card(original)
    s.archive_card("mem_000001", reason="superseded by telemetry review")
    archived = s.read_archived()
    assert len(archived) == 1
    assert archived[0] == original


# ----------------------------------------------------------------- load behaviour


def test_load_empty_store_returns_no_cards_no_warnings(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    cards, warnings = s.load()
    assert cards == []
    assert warnings == []


def test_load_reports_warnings_for_corrupt_active_entries(tmp_path: Path) -> None:
    s = make_store(tmp_path)
    s.storage_root.mkdir(parents=True, exist_ok=True)
    s.active_path.write_text('[{"card_id": "bad"}]', encoding="utf-8")
    cards, warnings = s.load()
    assert cards == []
    assert len(warnings) == 1


# ----------------------------------------------------------- review log crash-safety


def test_review_log_batch_completed_not_orphaned(tmp_path: Path) -> None:
    log = ReviewLog(tmp_path / "memory_review_log.jsonl", clock=_clock())
    log.append_batch_started("batch_1", 2, ["edit_card", "archive_card"])
    log.append_batch_completed("batch_1")
    orphaned, record = log.last_batch_orphaned()
    assert orphaned is False
    assert record is None


def test_review_log_orphaned_batch_detected(tmp_path: Path) -> None:
    log = ReviewLog(tmp_path / "memory_review_log.jsonl", clock=_clock())
    log.append_batch_started("batch_1", 3, ["edit_card"])
    orphaned, record = log.last_batch_orphaned()
    assert orphaned is True
    assert record is not None
    assert record["batch_id"] == "batch_1"


def test_review_log_maintenance_failed_appended(tmp_path: Path) -> None:
    log = ReviewLog(tmp_path / "memory_review_log.jsonl", clock=_clock())
    log.append_maintenance_failed("validator timeout")
    orphaned, _ = log.last_batch_orphaned()
    assert orphaned is False
