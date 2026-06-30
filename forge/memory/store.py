from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .._lock import flock_exclusive

from .cards import MemoryCard
from .feedback_store import FeedbackStore
from .review_log import ReviewLog
from .validation import validate_memory_text
from ..config import default_config


class MemoryStore:
    """Persistent memory-card store with active/deleted split and global id allocator.

    Storage layout (under ``storage_root``)::

        memory_cards.json          # active cards (atomic JSON rewrite + lock)
        memory_cards_deleted.json  # archived cards (atomic JSON rewrite + lock)
        memory_feedback.jsonl      # finish-time card ratings (append-only)
        memory_review_log.jsonl    # /review-memory operations log (append-only)
        memory_id_counter.json     # global sequential ID allocator

    The constructor accepts the legacy ``cards.jsonl`` path argument unchanged:
    a ``.jsonl``/``.json`` suffix means the parent directory is the storage root,
    otherwise the path itself is treated as the storage root directory.
    """

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        if path.suffix in (".jsonl", ".json"):
            self.storage_root = path.parent
        else:
            self.storage_root = path
        self.active_path = self.storage_root / "memory_cards.json"
        self.deleted_path = self.storage_root / "memory_cards_deleted.json"
        self.counter_path = self.storage_root / "memory_id_counter.json"
        self.feedback_path = self.storage_root / "memory_feedback.jsonl"
        self.review_log_path = self.storage_root / "memory_review_log.jsonl"
        self.feedback = FeedbackStore(self.feedback_path, clock=clock)
        self.review_log = ReviewLog(self.review_log_path, clock=clock)
        self._corruption_warnings: list[str] = []

    @property
    def corruption_warnings(self) -> list[str]:
        """Warnings collected during corrupt-record reads (cleared on each read)."""
        return list(self._corruption_warnings)

    # ------------------------------------------------------------------ helpers

    def _timestamp(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).isoformat().replace("+00:00", "Z")

    @contextmanager
    def _mutation_lock(self):
        self.storage_root.mkdir(parents=True, exist_ok=True)
        with (self.storage_root / ".memory_store.lock").open("a+", encoding="utf-8") as lock:
            flock_exclusive(lock)
            yield

    def _read_json(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        if not text.strip():
            return []
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError, TypeError):
            self._corruption_warnings.append(
                f"skipped corrupt JSON in {path.name}: unparseable content")
            return []
        if not isinstance(data, list):
            self._corruption_warnings.append(
                f"skipped non-list JSON in {path.name}: got {type(data).__name__}")
            return []
        return data

    def _write_json(self, path: Path, data: list[dict[str, Any]]) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(path.name + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            flock_exclusive(lock)
            tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
            with tmp.open("w", encoding="utf-8") as stream:
                json.dump(data, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)

    # ------------------------------------------------------------------- reading

    def read_active(self) -> list[MemoryCard]:
        self._corruption_warnings.clear()
        cards: list[MemoryCard] = []
        for number, entry in enumerate(self._read_json(self.active_path), 1):
            try:
                cards.append(MemoryCard.from_dict(entry))
            except (ValueError, TypeError, KeyError) as exc:
                self._corruption_warnings.append(
                    f"skipped corrupt memory card at active[{number}]: {exc}")
                continue
        return cards

    def read_archived(self) -> list[MemoryCard]:
        self._corruption_warnings.clear()
        cards: list[MemoryCard] = []
        for wrapper in self._read_json(self.deleted_path):
            try:
                cards.append(MemoryCard.from_dict(wrapper["card"]))
            except (ValueError, TypeError, KeyError) as exc:
                self._corruption_warnings.append(
                    f"skipped corrupt archived card: {exc}")
                continue
        return cards

    def load(self) -> tuple[list[MemoryCard], list[str]]:
        self._corruption_warnings.clear()
        cards: list[MemoryCard] = []
        warnings: list[str] = []
        for number, entry in enumerate(self._read_json(self.active_path), 1):
            try:
                cards.append(MemoryCard.from_dict(entry))
            except (ValueError, TypeError, KeyError) as exc:
                warnings.append(f"skipped corrupt memory card at index {number}: {exc}")
        if self._corruption_warnings:
            warnings.extend(self._corruption_warnings)
        return cards, warnings

    # ------------------------------------------------------------------- id alloc

    def next_id(self) -> str:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        lock_path = self.counter_path.with_name(self.counter_path.name + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            flock_exclusive(lock)
            last = 0
            if self.counter_path.exists():
                try:
                    raw = json.loads(self.counter_path.read_text(encoding="utf-8"))
                    last = int(raw.get("last_id", 0))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    last = 0
            value = last + 1
            tmp = self.counter_path.with_name(
                self.counter_path.name + f".{os.getpid()}.tmp")
            with tmp.open("w", encoding="utf-8") as stream:
                json.dump({"last_id": value}, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.counter_path)
            return f"mem_{value:06d}"

    # ------------------------------------------------------------------- mutation

    def add_card(self, card: MemoryCard) -> None:
        saved = list(self._corruption_warnings)
        try:
            with self._mutation_lock():
                active = self.read_active()
                if any(current.card_id == card.card_id for current in active):
                    raise ValueError(f"duplicate active card_id: {card.card_id}")
                active.append(card)
                self._write_json(self.active_path, [c.to_dict() for c in active])
        finally:
            self._corruption_warnings.extend(saved)

    def edit_card(self, card_id: str, *, memory: str | None = None,
                  why: str | None = None, avoid: str | None = None,
                  use_as: str | None = None, confidence: str | None = None,
                  applies_when: Any = None) -> MemoryCard:
        saved = list(self._corruption_warnings)
        try:
            with self._mutation_lock():
                active = self.read_active()
                for index, current in enumerate(active):
                    if current.card_id != card_id:
                        continue
                    updates: dict[str, Any] = {}
                    if memory is not None:
                        cfg = default_config()
                        err = validate_memory_text(memory, cfg.memory.validation)
                        if err is not None:
                            raise ValueError(f"invalid memory text: {err}")
                        updates["memory"] = memory
                    if why is not None:
                        updates["why"] = why
                    if avoid is not None:
                        updates["avoid"] = avoid
                    if use_as is not None:
                        updates["use_as"] = use_as
                    if confidence is not None:
                        updates["confidence"] = confidence
                    if applies_when is not None:
                        updates["applies_when"] = applies_when
                    updated = replace(current, **updates)
                    active[index] = updated
                    self._write_json(self.active_path, [c.to_dict() for c in active])
                    return updated
            raise KeyError(card_id)
        finally:
            self._corruption_warnings.extend(saved)

    def archive_card(self, card_id: str, reason: str) -> MemoryCard:
        saved = list(self._corruption_warnings)
        try:
            with self._mutation_lock():
                active = self.read_active()
                target = next((card for card in active if card.card_id == card_id), None)
                if target is None:
                    raise KeyError(card_id)
                wrappers = self._read_json(self.deleted_path)
                wrappers.append({"card": target.to_dict(), "reason": reason,
                                 "archived_at": self._timestamp()})
                self._write_json(self.deleted_path, wrappers)
                self._write_json(
                    self.active_path,
                    [c.to_dict() for c in active if c.card_id != card_id],
                )
                return target
        finally:
            self._corruption_warnings.extend(saved)

    def restore_card(self, card_id: str, reason: str) -> MemoryCard:
        saved = list(self._corruption_warnings)
        try:
            with self._mutation_lock():
                return self._restore_card_locked(card_id, reason)
        finally:
            self._corruption_warnings.extend(saved)

    def _restore_card_locked(self, card_id: str, reason: str) -> MemoryCard:
        wrappers = self._read_json(self.deleted_path)
        target_wrapper: dict[str, Any] | None = None
        remaining_wrappers: list[dict[str, Any]] = []
        for wrapper in wrappers:
            try:
                if MemoryCard.from_dict(wrapper["card"]).card_id == card_id:
                    target_wrapper = wrapper
                    continue
            except (ValueError, TypeError, KeyError):
                pass
            remaining_wrappers.append(wrapper)
        if target_wrapper is None:
            raise KeyError(card_id)
        target = MemoryCard.from_dict(target_wrapper["card"])
        restored = replace(target, superseded_by=None)
        active = self.read_active()
        active.append(restored)
        # Write active first so a crash between writes leaves the card in both
        # stores (recoverable duplicate) rather than neither (data loss).
        self._write_json(self.active_path, [c.to_dict() for c in active])
        self._write_json(self.deleted_path, remaining_wrappers)
        return restored

    def merge_cards(self, card_ids: list[str], new_card: MemoryCard, *,
                    kind: str = "merge", reason: str = "") -> MemoryCard:
        saved = list(self._corruption_warnings)
        try:
            with self._mutation_lock():
                return self._merge_cards_locked(card_ids, new_card, kind=kind, reason=reason)
        finally:
            self._corruption_warnings.extend(saved)

    def _merge_cards_locked(self, card_ids: list[str], new_card: MemoryCard, *,
                            kind: str, reason: str) -> MemoryCard:
        active = self.read_active()
        by_id = {c.card_id: c for c in active}
        sources: list[MemoryCard] = []
        for cid in card_ids:
            if cid not in by_id:
                raise KeyError(cid)
            sources.append(by_id[cid])
        new_id = new_card.card_id.strip() or self.next_id()
        union_ids: list[str] = []
        seen: set[str] = set()
        for source in sources:
            for tid in source.source_task_ids:
                if tid not in seen:
                    seen.add(tid)
                    union_ids.append(tid)
        for tid in new_card.source_task_ids:
            if tid not in seen:
                seen.add(tid)
                union_ids.append(tid)
        final_card = replace(
            new_card,
            card_id=new_id,
            supersedes=list(card_ids),
            source_task_ids=union_ids,
        )
        archived_ids = set(card_ids)
        remaining = [c for c in active if c.card_id not in archived_ids]
        remaining.append(final_card)
        wrappers = self._read_json(self.deleted_path)
        archive_reason = reason or kind
        ts = self._timestamp()
        for source in sources:
            archived = replace(source, superseded_by=new_id)
            wrappers.append({
                "card": archived.to_dict(),
                "reason": archive_reason,
                "archived_at": ts,
            })
        self._write_json(self.deleted_path, wrappers)
        self._write_json(self.active_path, [c.to_dict() for c in remaining])
        return final_card

    # ----------------------------------------------------------------- feedback

    def read_feedback_aggregate(self) -> dict[str, dict[str, int]]:
        aggregate: dict[str, dict[str, int]] = {}
        for record in self.feedback.read_feedback():
            cid = record.get("card_id")
            if not isinstance(cid, str) or not cid:
                continue
            bucket = aggregate.setdefault(
                cid, {"helpful": 0, "unused": 0, "misleading": 0, "unknown": 0, "n": 0})
            bucket["n"] += 1
            rating = record.get("rating")
            if isinstance(rating, str) and rating in bucket:
                bucket[rating] += 1
            else:
                bucket["unknown"] += 1
        return aggregate


def rank(cards: Iterable[MemoryCard], repo_id: str, task_text: str,
         files: list[str], risks: list[str] | None = None
         ) -> list[tuple[int, MemoryCard]]:
    """Scoring-backed compat shim delegating to :func:`scoring.select_cards`.

    ``service.py`` now calls ``scoring.select_cards`` directly.  This shim
    This shim remains available for tests and external consumers.  It uses an **empty** feedback aggregate (so ``agent_score = 0.5`` and
    ``det_score = 0.5`` for every card — uniform quality).  Ordering is driven
    by ``relevance`` (repo-isolated, task/file/risk aware) via
    ``select_cards``.  Returns ``list[tuple[int, MemoryCard]]`` where the int
    is ``round(final_score * 1000)`` (the actual score is a float; scaled to
    int for the legacy tuple contract).
    """
    from types import SimpleNamespace

    from .scoring import final_score, select_cards
    from ..config import default_config

    cards_list = list(cards)
    config = default_config().memory.scoring
    task = SimpleNamespace(
        repo_root=repo_id, task_text=task_text, expected_files=files, risks=risks
    )
    aggregate: dict[str, dict[str, int]] = {}

    selected_ids = select_cards(cards_list, task, aggregate, config)
    by_id = {c.card_id: c for c in cards_list}

    result: list[tuple[int, MemoryCard]] = []
    for cid in selected_ids:
        card_obj = by_id[cid]
        score = final_score(card_obj, aggregate, config, repo_id, task_text, files, risks)
        result.append((int(round(score * 1000)), card_obj))
    return result
