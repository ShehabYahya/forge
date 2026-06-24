from __future__ import annotations

"""Per-operation validation for the /review-memory batch apply flow.

Each ``validate_<op>`` function returns a ``list[str]`` of human-readable
reasons (empty == valid). A bad operation never rejects its siblings: the
service applies valid ops even when siblings are rejected (partial apply).

Anti-vague checks reuse T2's ``validate_memory_text`` / ``validate_why`` /
``normalize_memory_text`` / ``has_concrete_anchor`` — there is no
re-implementation of the blocklist here.
"""

import re
from typing import Any

from ..config import ForgeConfig
from .cards import MemoryCard
from .maintenance_schema import (
    ArchiveCardOp,
    CompactCardsOp,
    CreateMemoryCardOp,
    CreatePatternCardOp,
    EditCardOp,
    MergeCardsOp,
    RestoreCardOp,
)
from .scoring import agent_score
from .store import MemoryStore
from .validation import (
    has_concrete_anchor,
    normalize_memory_text,
    validate_memory_text,
    validate_why,
)

# Restore reasons must reference why the archive was wrong.
_RESTORE_KEYWORDS: tuple[str, ...] = (
    "misread", "mistake", "wrong", "error", "incorrect", "should not have",
    "shouldn't have", "erroneous",
)

# Pattern ``why`` must reference the recurrence: a number >=2 OR one of these
# words.
_RECURRENCE_WORDS: tuple[str, ...] = ("multiple", "recurring", "repeated", "across")
_NUMBER_RE = re.compile(r"\d+")


def _find_card(active: list[MemoryCard], card_id: str) -> MemoryCard | None:
    return next((c for c in active if c.card_id == card_id), None)


def _find_archived(archived: list[MemoryCard], card_id: str) -> MemoryCard | None:
    return next((c for c in archived if c.card_id == card_id), None)


def _confidence_is_valid(value: str | None) -> bool:
    return value is None or value in ("high", "medium", "low")


def _memory_text_reason(text: str | None, config: ForgeConfig,
                        field_label: str = "memory") -> str | None:
    """Run T2's ``validate_memory_text`` on a (possibly-None) text field.

    Returns ``None`` when the field is ``None`` (no edit) or valid. Returns a
    reason string otherwise.
    """
    if text is None:
        return None
    reason = validate_memory_text(text, config.memory.validation)
    if reason is None:
        return None
    return reason


# --------------------------------------------------------------------------- edit


def validate_edit(op: EditCardOp, store: MemoryStore,
                  config: ForgeConfig) -> list[str]:
    reasons: list[str] = []
    if not op.card_id:
        reasons.append("edit_card requires a card_id")
        return reasons
    active = store.read_active()
    target = _find_card(active, op.card_id)
    if target is None:
        reasons.append(f"edit_card card_id '{op.card_id}' not found in active cards")
        return reasons
    # No-op edits (all fields None) are rejected — a maintenance op must do work.
    if all(getattr(op, name) is None
           for name in ("memory", "why", "avoid", "use_as", "confidence")):
        reasons.append("edit_card must change at least one field")
    if not _confidence_is_valid(op.confidence):
        reasons.append("confidence must be one of high/medium/low")
    mem_reason = _memory_text_reason(op.memory, config)
    if mem_reason is not None:
        reasons.append(mem_reason)
    if op.why is not None:
        why_reason = validate_why(op.why, config.memory.validation)
        if why_reason is not None:
            reasons.append(why_reason)
    # why/avoid/use_as length sanity: when provided and non-empty, enforce a
    # light floor so agents cannot blank a card into vagueness. The T2
    # ``validate_why`` already enforces why_min_chars for ``why``; for
    # avoid/use_as we apply the same floor.
    if op.avoid is not None and op.avoid.strip() and len(op.avoid) < config.memory.validation.why_min_chars:
        reasons.append(
            f"avoid must be at least {config.memory.validation.why_min_chars} chars when provided"
        )
    if op.use_as is not None and op.use_as.strip() and len(op.use_as) < config.memory.validation.why_min_chars:
        reasons.append(
            f"use_as must be at least {config.memory.validation.why_min_chars} chars when provided"
        )
    return reasons


# ------------------------------------------------------------------------ archive


def validate_archive(op: ArchiveCardOp, store: MemoryStore,
                     config: ForgeConfig,
                     feedback_aggregate: dict[str, dict[str, int]]) -> list[str]:
    reasons: list[str] = []
    if not op.card_id:
        reasons.append("archive_card requires a card_id")
        return reasons
    if not op.reason.strip():
        reasons.append("archive_card requires a recorded reason referencing telemetry evidence")
    active = store.read_active()
    target = _find_card(active, op.card_id)
    if target is None:
        reasons.append(f"archive_card card_id '{op.card_id}' not found in active cards")
        return reasons
    # High-rated guard: agent_score >= threshold AND n >= min_observations.
    bucket = feedback_aggregate.get(op.card_id, {})
    n = bucket.get("n", 0)
    score = agent_score(target, feedback_aggregate, config.memory.scoring)
    if score >= config.memory.maintenance.review.high_rated_threshold and \
            n >= config.memory.maintenance.review.high_rated_min_observations:
        reasons.append(
            f"card '{op.card_id}' is high-rated (agent_score={score:.2f}, n={n}) "
            "and cannot be archived outright; compact or merge instead"
        )
    return reasons


# ------------------------------------------------------------------------ restore


def validate_restore(op: RestoreCardOp, store: MemoryStore,
                     config: ForgeConfig) -> list[str]:
    reasons: list[str] = []
    if not op.card_id:
        reasons.append("restore_archived_card requires a card_id")
        return reasons
    if not op.reason.strip():
        reasons.append("restore_archived_card requires a strong recorded reason")
        return reasons
    archived = store.read_archived()
    target = _find_archived(archived, op.card_id)
    if target is None:
        reasons.append(
            f"restore_archived_card card_id '{op.card_id}' not found in archived cards"
        )
        return reasons
    lowered = op.reason.lower()
    if not any(keyword in lowered for keyword in _RESTORE_KEYWORDS):
        reasons.append(
            "restore reason must reference why the archive was wrong "
            "(e.g., 'misread', 'mistake', 'wrong', 'error')"
        )
    return reasons


# ---------------------------------------------------------- merge / compact shared


def _validate_combine(op: MergeCardsOp | CompactCardsOp, store: MemoryStore,
                      config: ForgeConfig, op_name: str) -> list[str]:
    reasons: list[str] = []
    if not op.card_ids or len(op.card_ids) < 2:
        reasons.append(f"{op_name} requires at least 2 card_ids")
    if not op.memory.strip():
        reasons.append(f"{op_name} requires a non-empty memory")
    else:
        mem_reason = validate_memory_text(op.memory, config.memory.validation)
        if mem_reason is not None:
            reasons.append(mem_reason)
    if op.why.strip():
        why_reason = validate_why(op.why, config.memory.validation)
        if why_reason is not None:
            reasons.append(why_reason)
    if not _confidence_is_valid(op.confidence):
        reasons.append("confidence must be one of high/medium/low")
    if op.card_ids:
        active = store.read_active()
        active_ids = {c.card_id for c in active}
        for cid in op.card_ids:
            if cid not in active_ids:
                reasons.append(f"{op_name} card_id '{cid}' not found in active cards")
                break
        # Distinct ids only.
        if len(set(op.card_ids)) != len(op.card_ids):
            reasons.append(f"{op_name} card_ids must be distinct")
    return reasons


def validate_merge(op: MergeCardsOp, store: MemoryStore,
                   config: ForgeConfig) -> list[str]:
    return _validate_combine(op, store, config, "merge_cards")


def validate_compact(op: CompactCardsOp, store: MemoryStore,
                     config: ForgeConfig) -> list[str]:
    return _validate_combine(op, store, config, "compact_cards")


# --------------------------------------------------------------- create_pattern


def validate_create_pattern(op: CreatePatternCardOp, store: MemoryStore,
                            config: ForgeConfig, *,
                            tasks_by_id: dict[str, Any],
                            telemetry_task_ids: set[str]) -> list[str]:
    reasons: list[str] = []
    cfg = config.memory.maintenance.review
    # memory structural + anti-vague (T2).
    if not op.memory.strip():
        reasons.append("create_pattern_card requires a non-empty memory")
    else:
        mem_reason = validate_memory_text(op.memory, config.memory.validation)
        if mem_reason is not None:
            reasons.append(mem_reason)
    # why min 20 chars + recurrence reference.
    if not op.why.strip():
        reasons.append("create_pattern_card requires a non-empty why")
    else:
        why_reason = validate_why(op.why, config.memory.validation)
        if why_reason is not None:
            reasons.append(why_reason)
        else:
            lowered = op.why.lower()
            has_number = any(int(m.group(0)) >= 2 for m in _NUMBER_RE.finditer(op.why))
            has_word = any(word in lowered for word in _RECURRENCE_WORDS)
            if not has_number and not has_word:
                reasons.append(
                    "pattern why must reference the recurrence "
                    "(a number >=2 or 'multiple'/'recurring'/'repeated'/'across')"
                )
    # >=2 source tasks (configurable).
    if len(op.source_task_ids) < cfg.pattern_min_source_tasks:
        reasons.append(
            f"pattern requires >={cfg.pattern_min_source_tasks} source tasks; "
            f"only {len(op.source_task_ids)} found"
        )
    # Each source task must exist, be finished (terminal state), and have telemetry.
    if op.source_task_ids:
        if len(set(op.source_task_ids)) != len(op.source_task_ids):
            reasons.append("source_task_ids must be distinct")
        for tid in op.source_task_ids:
            task = tasks_by_id.get(tid)
            if task is None:
                reasons.append(f"source_task_id '{tid}' not found in tasks.jsonl")
                break
            state = getattr(task, "state", None)
            terminal = {"completed", "failed", "degraded"}
            if state not in terminal:
                reasons.append(
                    f"source_task_id '{tid}' is not in a terminal state (got '{state}')"
                )
                break
            if tid not in telemetry_task_ids:
                reasons.append(
                    f"source_task_id '{tid}' has no telemetry events"
                )
                break
    # Concrete anchor in memory text.
    if op.memory.strip() and not has_concrete_anchor(op.memory):
        reasons.append("pattern memory must contain a concrete anchor (file path, command, tool, function, or module)")
    # Duplicate detection against active cards (normalized memory text).
    if op.memory.strip():
        norm = normalize_memory_text(op.memory)
        if norm:
            for card in store.read_active():
                if normalize_memory_text(card.memory) == norm:
                    reasons.append(
                        f"pattern memory duplicates existing card '{card.card_id}'"
                    )
                    break
    # Confidence enum.
    if not _confidence_is_valid(op.confidence):
        reasons.append("confidence must be one of high/medium/low")
    return reasons


# --------------------------------------------------------------- create_memory_card


def validate_create_memory(op: CreateMemoryCardOp, store: MemoryStore,
                           config: ForgeConfig, *,
                           tasks_by_id: dict[str, Any],
                           telemetry_task_ids: set[str]) -> list[str]:
    reasons: list[str] = []
    cfg = config.memory.maintenance.review
    # memory structural + anti-vague (T2).
    if not op.memory.strip():
        reasons.append("create_memory_card requires a non-empty memory")
    else:
        mem_reason = validate_memory_text(op.memory, config.memory.validation)
        if mem_reason is not None:
            reasons.append(mem_reason)
    # why min 20 chars.
    if not op.why.strip():
        reasons.append("create_memory_card requires a non-empty why")
    else:
        why_reason = validate_why(op.why, config.memory.validation)
        if why_reason is not None:
            reasons.append(why_reason)
    # Exactly 1 source task (create_pattern_card handles >=2).
    if len(op.source_task_ids) != 1:
        reasons.append(
            f"create_memory_card requires exactly 1 source task; "
            f"got {len(op.source_task_ids)}"
        )
    # Each source task must exist, be terminal (completed/failed/degraded),
    # and have telemetry.
    if op.source_task_ids:
        if len(set(op.source_task_ids)) != len(op.source_task_ids):
            reasons.append("source_task_ids must be distinct")
        for tid in op.source_task_ids:
            task = tasks_by_id.get(tid)
            if task is None:
                reasons.append(f"source_task_id '{tid}' not found in tasks.jsonl")
                break
            state = getattr(task, "state", None)
            terminal = {"completed", "failed", "degraded"}
            if state not in terminal:
                reasons.append(
                    f"source_task_id '{tid}' is not in a terminal state (got '{state}')"
                )
                break
            if tid not in telemetry_task_ids:
                reasons.append(
                    f"source_task_id '{tid}' has no telemetry events"
                )
                break
    # Concrete anchor in memory text.
    if op.memory.strip() and not has_concrete_anchor(op.memory):
        reasons.append("memory must contain a concrete anchor (file path, command, tool, function, or module)")
    # Duplicate detection against active cards (normalized memory text).
    if op.memory.strip():
        norm = normalize_memory_text(op.memory)
        if norm:
            for card in store.read_active():
                if normalize_memory_text(card.memory) == norm:
                    reasons.append(
                        f"memory duplicates existing card '{card.card_id}'"
                    )
                    break
    # Confidence enum.
    if not _confidence_is_valid(op.confidence):
        reasons.append("confidence must be one of high/medium/low")
    return reasons
