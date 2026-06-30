from __future__ import annotations

import os
from typing import Any

from ..config import ForgeConfig
from ..memory.cards import AppliesWhen, MemoryCard, _git_remote_url
from ..memory.store import MemoryStore
from ..memory.validation import validate_memory_text, validate_why

# --------------------------------------------------------------------------- helpers
#
# The factory is the only place that builds a MemoryCard from a finish_task
# draft. It is deliberately deterministic: no model calls, no wall-clock reads.
# Every derived field is a pure function of (task, review, honesty, draft).

# Small, deterministic keyword -> task_type map. Substring match on the
# lowercased task_text. Order is irrelevant: results are collected into a set
# and emitted sorted. "Examples" from the spec are the authoritative set.
_KEYWORD_MAP: tuple[tuple[str, str], ...] = (
    ("test", "testing"),
    ("doc", "docs"),
    ("document", "docs"),
    ("fix", "bugfix"),
    ("bug", "bugfix"),
    ("refactor", "refactor"),
    ("plugin", "plugin"),
    ("tool", "tooling"),
    ("tooling", "tooling"),
    ("memory", "memory"),
    ("config", "config"),
    ("review", "review"),
    ("build", "build"),
    ("packag", "build"),
    ("telemetry", "telemetry"),
)

# Extensions that imply a real source file even without a path separator.
# Mirrors the set recognised by validation.has_concrete_anchor.
_SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".ts", ".js", ".json", ".md", ".toml", ".yaml", ".yml",
    ".go", ".rs", ".java", ".rb", ".sh", ".txt",
})


def classify_task_types(task_text: str) -> list[str]:
    """Keyword classification of ``task_text`` into task_types.

    Uses a small deterministic keyword map (substring match on the lowercased
    text). Returns a sorted unique list. Returns ``['general']`` when nothing
    matches or the input is empty/non-string.
    """
    if not isinstance(task_text, str) or not task_text.strip():
        return ["general"]
    lowered = task_text.lower()
    found: set[str] = set()
    for keyword, label in _KEYWORD_MAP:
        if keyword in lowered:
            found.add(label)
    return sorted(found) if found else ["general"]


def derive_modules(changed_files: list[str]) -> list[str]:
    """Top-level directory segment of each changed file.

    ``forge/mcp_server.py`` -> ``forge``; ``a/b/c.py`` -> ``a``; ``file.py``
    (no directory) is skipped. Returns sorted unique non-empty segments.
    """
    modules: set[str] = set()
    for path in changed_files or []:
        if not isinstance(path, str) or not path:
            continue
        if "/" in path:
            top = path.split("/", 1)[0]
            if top:
                modules.add(top)
    return sorted(modules)


def is_repo_specific(files: list[str]) -> bool:
    """Return True when every file looks repo-specific.

    A file looks repo-specific when it contains a ``/`` path separator OR has a
    known source extension. Empty input -> False (treated as ``transferable``):
    with no file evidence the card is not pinned to this repo's layout.
    """
    if not files:
        return False
    for path in files:
        if not isinstance(path, str) or not path:
            return False
        has_slash = "/" in path
        _, ext = os.path.splitext(path)
        if not (has_slash or ext.lower() in _SOURCE_EXTENSIONS):
            return False
    return True


def derive_confidence(finish_claim_honesty: str, review: dict | None) -> str | None:
    """Derive card confidence per the spec table.

    Returns ``None`` to signal "do not create" (only for ``mismatch``).
    ``review`` is the verdict dict (with ``passed`` bool and ``blockers`` list)
    or ``None``.
    """
    if finish_claim_honesty == "mismatch":
        return None
    if finish_claim_honesty == "verified":
        # Independently-observed pass from transcript evidence.
        # Now reachable via session_digest with observed passing tests.
        if review is not None and review.get("passed") is True:
            return "high"
        return "low"
    if finish_claim_honesty == "unverified":
        if review is not None and review.get("passed") is True:
            return "medium"
        return "low"
    if finish_claim_honesty == "honest_failure":
        blockers = review.get("blockers") if review else None
        if blockers:
            return "medium"
        return "low"
    # Unknown honesty string: be conservative rather than overclaiming.
    return "low"


def _risk_patterns_from(draft: dict, review: dict | None) -> list[str]:
    """Agent-provided risk_patterns win; otherwise derive from review blockers."""
    provided = draft.get("risk_patterns")
    if isinstance(provided, list) and provided:
        return [item for item in provided if isinstance(item, str)]
    blockers = review.get("blockers") if review else None
    if isinstance(blockers, list):
        return [item for item in blockers if isinstance(item, str)]
    return []


def create_card_from_draft(
    task: Any,
    review: dict | None,
    honesty: tuple[str, str],
    draft: dict | None,
    store: MemoryStore,
    config: ForgeConfig,
    timestamp: str,
) -> dict:
    """Create a memory card from a finish_task ``memory_draft``.

    Returns ``{"ok": True, "card": MemoryCard}`` on success, or
    ``{"ok": True, "warning": str}`` when the draft is rejected (the task
    outcome is never affected by card creation failure). When no draft is
    provided, returns ``{"ok": True}`` and creates no card.

    Parameters
    ----------
    task:
        Object with ``.task_id``, ``.repo_root``, ``.task_text``.
    review:
        Verdict dict (``changed_files``, ``blockers``, ``passed``) or ``None``.
    honesty:
        ``(claim_evidence_status, finish_claim_honesty)`` from ``derive_honesty``.
    draft:
        ``memory_draft`` dict or ``None``.
    store:
        ``MemoryStore``; ``next_id`` and ``add_card`` are called on success.
    config:
        ``ForgeConfig``; ``config.memory.validation`` drives text validation.
    timestamp:
        ``created_at`` (ISO 8601 string).
    """
    if draft is None:
        return {"ok": True}

    finish_claim_honesty = honesty[1] if isinstance(honesty, tuple) and len(honesty) > 1 else ""

    # Mismatch: the agent's success claim contradicts the evidence. Never create
    # a card; finish still succeeds with a warning.
    if finish_claim_honesty == "mismatch":
        return {"ok": True, "warning": "memory_draft rejected: claim contradicts evidence"}

    validation = config.memory.validation

    memory = draft.get("memory", "")
    reason = validate_memory_text(memory, validation)
    if reason is not None:
        return {"ok": True, "warning": f"memory_draft rejected: {reason}"}

    why_reason = validate_why(draft.get("why"), validation)
    if why_reason is not None:
        return {"ok": True, "warning": f"memory_draft rejected: {why_reason}"}

    confidence = derive_confidence(finish_claim_honesty, review)
    if confidence is None:
        # Defensive: only derive_confidence("mismatch", ...) returns None, and
        # that case is handled above. Keep the guard so the contract holds even
        # if the honesty vocabulary grows.
        return {"ok": True, "warning": "memory_draft rejected: claim contradicts evidence"}

    files: list[str] = []
    if review is not None:
        changed = review.get("changed_files")
        if isinstance(changed, list):
            files = [item for item in changed if isinstance(item, str)]

    entry_type = "pitfall_memory" if finish_claim_honesty == "honest_failure" else "validation_memory"
    transferability = "local_only" if is_repo_specific(files) else "transferable"

    applies_when = AppliesWhen(
        task_types=classify_task_types(getattr(task, "task_text", "") or ""),
        files=files,
        modules=derive_modules(files),
        risk_patterns=_risk_patterns_from(draft, review),
    )

    card = MemoryCard(
        card_id=store.next_id(),
        memory=memory,
        why=draft.get("why") or "",
        avoid=draft.get("avoid") or "",
        use_as="",
        entry_type=entry_type,
        transferability=transferability,
        source_repo_root=getattr(task, "repo_root", "") or "",
        source_repo_id=_git_remote_url(getattr(task, "repo_root", "") or ""),
        applies_when=applies_when,
        confidence=confidence,
        source_task_ids=[getattr(task, "task_id", "") or ""],
        supersedes=[],
        superseded_by=None,
        created_at=timestamp,
    )
    store.add_card(card)
    return {"ok": True, "card": card}
