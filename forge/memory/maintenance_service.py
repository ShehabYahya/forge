from __future__ import annotations

"""MaintenanceService — the backend for the /review-memory flow.

Owns:
  * ``get_maintenance_context`` — active + archived cards, orphaned batch
    status, recommendation data.
  * ``apply_memory_review_batch`` — partial-apply a batch of operations with
    per-op validation, crash-safe batch_started/batch_completed records.
  * ``finish_memory_maintenance`` — completed/failed exit path.
  * ``memory_maintenance_recommendation`` — T2 notification thresholds.

The service is intentionally pure-Python and deterministic: it never calls a
model, and the only wall-clock access is via the injected ``clock``. It talks
to the T3 ``MemoryStore`` API only — it does not touch JSON files directly
except for reading ``tasks.jsonl`` and ``telemetry.jsonl`` (which are owned by
``TaskStore`` / ``TelemetryWriter`` and read-only here).
"""

import json
import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from ..config import ForgeConfig
from ..memory.card_factory import classify_task_types, derive_modules, is_repo_specific
from .cards import AppliesWhen, MemoryCard
from .maintenance_schema import (
    OPERATION_TYPES,
    ArchiveCardOp,
    CompactCardsOp,
    CreateMemoryCardOp,
    CreatePatternCardOp,
    EditCardOp,
    MergeCardsOp,
    RestoreCardOp,
    parse_operation,
)
from .maintenance_validator import (
    validate_archive,
    validate_compact,
    validate_create_memory,
    validate_create_pattern,
    validate_edit,
    validate_merge,
    validate_restore,
)
from .store import MemoryStore


class MaintenanceService:
    def __init__(self, store: MemoryStore, config: ForgeConfig,
                 task_store: Any | None = None,
                 telemetry_path: Path | str | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.config = config
        self.task_store = task_store
        self.telemetry_path = Path(telemetry_path) if telemetry_path else None
        self.clock = clock

    # ------------------------------------------------------------------ helpers

    def _timestamp(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).isoformat().replace("+00:00", "Z")

    def _tasks_by_id(self) -> dict[str, Any]:
        if self.task_store is None:
            return {}
        result: dict[str, Any] = {}
        for task in self.task_store.all():
            tid = getattr(task, "task_id", None)
            if tid:
                result[tid] = task
        return result

    def _telemetry_task_ids(self) -> set[str]:
        """Return the set of task_ids that have at least one telemetry event."""
        return {
            record["task_id"] for record in self._telemetry_events()
            if isinstance(record.get("task_id"), str) and record["task_id"]
        }

    def _telemetry_events(self) -> list[dict[str, Any]]:
        if self.telemetry_path is None or not self.telemetry_path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            text = self.telemetry_path.read_text(encoding="utf-8")
        except OSError:
            return []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    # ------------------------------------------------------------- context read

    def get_maintenance_context(self) -> dict[str, Any]:
        active = self.store.read_active()
        archived = self.store.read_archived()
        orphaned, orphan_batch = self.store.review_log.last_batch_orphaned()
        recommendation = self.memory_maintenance_recommendation()
        return {
            "ok": True,
            "active_cards": [c.to_dict() for c in active],
            "archived_cards": [c.to_dict() for c in archived],
            "orphaned_batch": {
                "orphaned": orphaned,
                "batch": orphan_batch,
            } if orphaned else {"orphaned": False, "batch": None},
            "recommendation": recommendation,
            "tasks": [t.to_dict() for t in (self.task_store.all() if self.task_store else [])],
            "telemetry": self._telemetry_events(),
            "memory_gaps": self._memory_gaps(),
        }

    # -------------------------------------------------------- recommendation

    def memory_maintenance_recommendation(self) -> dict[str, Any]:
        cfg = self.config.memory.notifications
        active = self.store.read_active()
        feedback = self.store.read_feedback_aggregate()

        low_confidence = sum(1 for c in active if c.confidence == "low")
        misleading_count = 0
        for bucket in feedback.values():
            misleading_count += bucket.get("misleading", 0)

        # Staleness: cards whose card_id never appears in any review-log entry.
        # We treat "reviewed" loosely as "appears in any review_log record at all".
        stale_ids = self._stale_card_ids(cfg.stale_days)
        stale_count = len(stale_ids)

        reasons: list[str] = []
        if low_confidence >= cfg.low_confidence_threshold:
            reasons.append(
                f"{low_confidence} cards have unverified claims (low confidence)"
            )
        if misleading_count >= cfg.misleading_threshold:
            reasons.append(
                f"{misleading_count} cards were rated misleading in recent feedback"
            )
        if stale_count > 0 and stale_count >= 1:
            # Spec: cards not reviewed in >=30 days. One toast per threshold
            # crossing. We trigger whenever there is at least one stale card.
            reasons.append(
                f"{stale_count} cards haven't been reviewed in {cfg.stale_days}+ days"
            )
        gap_count = len(self._memory_gaps())
        if gap_count > 0:
            reasons.append(
                f"{gap_count} completed/failed/degraded tasks have no memory card"
            )
        recommend = bool(reasons)
        review_count = max(low_confidence, misleading_count, stale_count, gap_count)
        reason = " | ".join(reasons) if reasons else "no review thresholds crossed"
        return {
            "review_count": review_count,
            "recommend": recommend,
            "reason": reason,
        }

    def _stale_card_ids(self, stale_days: int) -> set[str]:
        """Card ids older than ``stale_days`` that have no review-log entry.

        A card is stale when (a) its ``created_at`` is more than ``stale_days``
        in the past AND (b) no review-log record references its card_id. The
        T3 review log records batch_started/batch_completed/maintenance_failed
        events (not per-card touches), so we scan every record's payload for
        the card_id string. Cards younger than ``stale_days`` are never stale
        regardless of review history — they are fresh.
        """
        if stale_days <= 0:
            return set()
        active = self.store.read_active()
        now = self.clock()
        cutoff = now - stale_days * 86400.0
        old_cards = [c for c in active if self._created_epoch(c) <= cutoff]
        if not old_cards:
            return set()
        try:
            records = self.store.review_log._read_all()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {c.card_id for c in old_cards}
        touched: set[str] = set()
        for record in records:
            blob = json.dumps(record, sort_keys=True)
            for card in old_cards:
                if card.card_id in blob:
                    touched.add(card.card_id)
        return {c.card_id for c in old_cards if c.card_id not in touched}

    @staticmethod
    def _created_epoch(card: MemoryCard) -> float:
        """Parse ``card.created_at`` to an epoch float; 0 on parse failure."""
        try:
            return datetime.fromisoformat(card.created_at.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError, AttributeError):
            return 0.0

    def _memory_gaps(self) -> list[dict[str, Any]]:
        """Terminal tasks with no memory card referencing them in source_task_ids."""
        if self.task_store is None:
            return []
        tasks = self.task_store.all()
        covered: set[str] = set()
        for card in self.store.read_active():
            covered.update(card.source_task_ids)
        for card in self.store.read_archived():
            covered.update(card.source_task_ids)
        gaps: list[dict[str, Any]] = []
        for task in tasks:
            if task.state not in {"completed", "failed", "degraded"}:
                continue
            if task.task_id in covered:
                continue
            review = task.review or {}
            gaps.append({
                "task_id": task.task_id,
                "task_text": task.task_text,
                "state": task.state,
                "changed_files": review.get("changed_files") or review.get("task_changed_files") or [],
                "blockers": review.get("blockers", []),
                "repo_root": task.repo_root,
            })
        return gaps

    # ------------------------------------------------------------- batch apply

    def apply_memory_review_batch(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(operations, list):
            return {"ok": False, "applied_count": 0, "rejected_count": 0,
                    "results": [], "error": "operations must be a list"}
        tasks_by_id = self._tasks_by_id()
        telemetry_task_ids = self._telemetry_task_ids()
        feedback_aggregate = self.store.read_feedback_aggregate()

        # Pre-parse all operations so we can record op_types in batch_started
        # even when some payloads are malformed.
        parsed: list[tuple[str, Any | None, dict[str, Any]]] = []
        op_types: list[str] = []
        for entry in operations:
            if not isinstance(entry, dict):
                parsed.append(("", None, {"__error": "operation must be an object"}))
                continue
            temp_id = entry.get("temp_id") or entry.get("id") or ""
            op = parse_operation(str(temp_id), entry)
            op_type = entry.get("operation") or ""
            if op_type:
                op_types.append(str(op_type))
            parsed.append((str(temp_id), op, entry))

        batch_seed = json.dumps(operations, sort_keys=True, default=str)
        batch_id = "batch_" + hashlib.sha256(
            f"{self.clock()}\0{batch_seed}".encode()
        ).hexdigest()[:24]
        self.store.review_log.append_batch_started(batch_id, len(parsed), op_types)
        results = self._apply_parsed(parsed, tasks_by_id, telemetry_task_ids,
                                     feedback_aggregate)
        self.store.review_log.append_batch_completed(batch_id, results)

        applied = sum(1 for r in results if r.get("status") == "applied")
        rejected = sum(1 for r in results if r.get("status") == "rejected")
        return {
            "ok": True,
            "batch_id": batch_id,
            "applied_count": applied,
            "rejected_count": rejected,
            "results": results,
        }

    def _apply_parsed(self, parsed, tasks_by_id, telemetry_task_ids,
                      feedback_aggregate) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for temp_id, op, raw in parsed:
            if op is None:
                if isinstance(raw, dict):
                    if not temp_id:
                        reason = "missing or empty temp_id"
                    elif "operation" not in raw:
                        reason = "operation type not specified"
                    elif raw.get("operation") not in OPERATION_TYPES:
                        reason = f"unknown operation type: '{raw.get('operation')}'"
                    else:
                        reason = "could not parse operation"
                else:
                    reason = "could not parse operation"
                op_type = raw.get("operation", "") if isinstance(raw, dict) else ""
                results.append({
                    "operation": op_type,
                    "temp_id": temp_id,
                    "status": "rejected",
                    "reasons": [reason],
                })
                continue
            try:
                result = self._apply_one(op, tasks_by_id, telemetry_task_ids,
                                         feedback_aggregate)
            except Exception as exc:  # pragma: no cover - defensive
                result = {
                    "operation": _op_name(op),
                    "temp_id": op.temp_id,
                    "status": "rejected",
                    "reasons": [f"backend error: {exc}"],
                }
            results.append(result)
        return results

    def _apply_one(self, op, tasks_by_id, telemetry_task_ids,
                   feedback_aggregate) -> dict[str, Any]:
        if isinstance(op, EditCardOp):
            reasons = validate_edit(op, self.store, self.config)
            if reasons:
                return {"operation": "edit_card", "card_id": op.card_id,
                        "temp_id": op.temp_id, "status": "rejected", "reasons": reasons}
            self.store.edit_card(
                op.card_id, memory=op.memory, why=op.why, avoid=op.avoid,
                use_as=op.use_as, confidence=op.confidence,
            )
            return {"operation": "edit_card", "card_id": op.card_id,
                    "temp_id": op.temp_id, "status": "applied"}
        if isinstance(op, ArchiveCardOp):
            reasons = validate_archive(op, self.store, self.config, feedback_aggregate)
            if reasons:
                return {"operation": "archive_card", "card_id": op.card_id,
                        "temp_id": op.temp_id, "status": "rejected", "reasons": reasons}
            self.store.archive_card(op.card_id, op.reason)
            return {"operation": "archive_card", "card_id": op.card_id,
                    "temp_id": op.temp_id, "status": "applied"}
        if isinstance(op, RestoreCardOp):
            reasons = validate_restore(op, self.store, self.config)
            if reasons:
                return {"operation": "restore_archived_card", "card_id": op.card_id,
                        "temp_id": op.temp_id, "status": "rejected", "reasons": reasons}
            self.store.restore_card(op.card_id, op.reason)
            return {"operation": "restore_archived_card", "card_id": op.card_id,
                    "temp_id": op.temp_id, "status": "applied"}
        if isinstance(op, (MergeCardsOp, CompactCardsOp)):
            op_name = "merge_cards" if isinstance(op, MergeCardsOp) else "compact_cards"
            reasons = (validate_merge(op, self.store, self.config) if isinstance(op, MergeCardsOp)
                       else validate_compact(op, self.store, self.config))
            if reasons:
                return {"operation": op_name, "temp_id": op.temp_id,
                        "status": "rejected", "reasons": reasons}
            new_card = self._build_combine_card(op)
            final_card = self.store.merge_cards(op.card_ids, new_card,
                                                kind=op.kind, reason=op.kind)
            return {"operation": op_name, "temp_id": op.temp_id,
                    "status": "applied", "card_id": final_card.card_id,
                    "supersedes": op.card_ids}
        if isinstance(op, CreatePatternCardOp):
            reasons = validate_create_pattern(
                op, self.store, self.config,
                tasks_by_id=tasks_by_id,
                telemetry_task_ids=telemetry_task_ids,
            )
            if reasons:
                return {"operation": "create_pattern_card", "temp_id": op.temp_id,
                        "status": "rejected", "reasons": reasons}
            new_card = self._build_pattern_card(op)
            self.store.add_card(new_card)
            return {"operation": "create_pattern_card", "temp_id": op.temp_id,
                    "status": "applied", "card_id": new_card.card_id}
        if isinstance(op, CreateMemoryCardOp):
            reasons = validate_create_memory(
                op, self.store, self.config,
                tasks_by_id=tasks_by_id,
                telemetry_task_ids=telemetry_task_ids,
            )
            if reasons:
                return {"operation": "create_memory_card", "temp_id": op.temp_id,
                        "status": "rejected", "reasons": reasons}
            task = tasks_by_id[op.source_task_ids[0]]
            new_card = self._build_memory_card(op, task)
            self.store.add_card(new_card)
            return {"operation": "create_memory_card", "temp_id": op.temp_id,
                    "status": "applied", "card_id": new_card.card_id}
        # Should never happen — parse_operation already filtered unknowns.
        return {"operation": _op_name(op), "temp_id": op.temp_id,
                "status": "rejected", "reasons": ["unsupported operation"]}

    # ------------------------------------------------------------- card builders

    def _build_memory_card(self, op: CreateMemoryCardOp, task: Any) -> MemoryCard:
        new_id = self.store.next_id()
        files = list(op.files)
        if not files:
            review = getattr(task, "review", None) or {}
            changed = review.get("changed_files") or review.get("task_changed_files")
            if isinstance(changed, list):
                files = [item for item in changed if isinstance(item, str)]
        task_text = getattr(task, "task_text", "") or ""
        modules = list(op.modules) if op.modules else derive_modules(files)
        task_types = list(op.task_types) if op.task_types else classify_task_types(task_text)
        entry_type = "pitfall_memory" if getattr(task, "state", "") in ("failed", "degraded") else "validation_memory"
        transferability = "local_only" if is_repo_specific(files) else "transferable"
        aw = AppliesWhen(
            task_types=task_types,
            files=files,
            modules=modules,
            risk_patterns=list(op.risk_patterns),
        )
        return MemoryCard(
            card_id=new_id,
            memory=op.memory,
            why=op.why,
            avoid=op.avoid,
            use_as=op.use_as,
            entry_type=entry_type,
            transferability=transferability,
            source_repo_root=getattr(task, "repo_root", "") or "",
            source_repo_id=getattr(task, "repo_root", "") or "",
            applies_when=aw,
            confidence=op.confidence,
            source_task_ids=[getattr(task, "task_id", "")],
            supersedes=[],
            superseded_by=None,
            created_at=self._timestamp(),
        )

    def _build_combine_card(self, op: MergeCardsOp | CompactCardsOp) -> MemoryCard:
        new_id = self.store.next_id()
        aw = AppliesWhen()
        return MemoryCard(
            card_id=new_id,
            memory=op.memory,
            why=op.why,
            avoid=op.avoid,
            use_as=op.use_as,
            entry_type="cross_task_pattern",
            transferability="transferable",
            source_repo_root="*",
            source_repo_id="*",
            applies_when=aw,
            confidence=op.confidence,
            source_task_ids=[],
            supersedes=[],
            superseded_by=None,
            created_at=self._timestamp(),
        )

    def _build_pattern_card(self, op: CreatePatternCardOp) -> MemoryCard:
        new_id = self.store.next_id()
        aw = AppliesWhen(
            task_types=list(op.task_types),
            files=list(op.files),
            modules=list(op.modules),
            risk_patterns=list(op.risk_patterns),
        )
        transferability = "transferable"
        return MemoryCard(
            card_id=new_id,
            memory=op.memory,
            why=op.why,
            avoid=op.avoid,
            use_as=op.use_as,
            entry_type="cross_task_pattern",
            transferability=transferability,
            source_repo_root="*",
            source_repo_id="*",
            applies_when=aw,
            confidence=op.confidence,
            source_task_ids=list(op.source_task_ids),
            supersedes=[],
            superseded_by=None,
            created_at=self._timestamp(),
        )

    # ----------------------------------------------------------- finish / failed

    def finish_memory_maintenance(self, status: str, reason: str = "") -> dict[str, Any]:
        if status == "failed":
            self.store.review_log.append_maintenance_failed(reason or "maintenance failed")
            # Resolve any orphaned batch so it does not persist forever.
            orphaned, orphan_batch = self.store.review_log.last_batch_orphaned()
            if orphaned and orphan_batch is not None:
                self.store.review_log.append_batch_completed(
                    orphan_batch.get("batch_id", ""), [])
            return {"ok": True, "status": "failed", "reason": reason}
        if status == "completed":
            self.store.review_log.append_log({
                "event": "maintenance_completed",
                "reason": reason,
                "timestamp": self._timestamp(),
            })
            return {"ok": True, "status": "completed", "reason": reason}
        return {"ok": False, "status": status,
                "error": "status must be 'completed' or 'failed'"}


_OP_NAMES = {
    "EditCardOp": "edit_card",
    "ArchiveCardOp": "archive_card",
    "RestoreCardOp": "restore_archived_card",
    "MergeCardsOp": "merge_cards",
    "CompactCardsOp": "compact_cards",
    "CreatePatternCardOp": "create_pattern_card",
    "CreateMemoryCardOp": "create_memory_card",
}


def _op_name(op) -> str:
    return _OP_NAMES.get(op.__class__.__name__, "") or op.__class__.__name__
