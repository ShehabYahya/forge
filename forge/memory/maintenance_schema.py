from __future__ import annotations

"""Operation dataclasses for the /review-memory batch apply flow.

Each operation is a small frozen dataclass. ``parse_operation`` maps an
agent-supplied dict (plus the agent-assigned ``temp_id`` for create ops) to the
right dataclass, returning ``None`` for an unknown operation type.

The schema is intentionally permissive about extra keys: only the fields the
backend cares about are pulled out, everything else is dropped.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EditCardOp:
    temp_id: str
    card_id: str
    memory: str | None = None
    why: str | None = None
    avoid: str | None = None
    use_as: str | None = None
    confidence: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveCardOp:
    temp_id: str
    card_id: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RestoreCardOp:
    temp_id: str
    card_id: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class MergeCardsOp:
    temp_id: str
    card_ids: list[str] = field(default_factory=list)
    memory: str = ""
    why: str = ""
    avoid: str = ""
    use_as: str = ""
    confidence: str = "medium"
    kind: str = "merge"


@dataclass(frozen=True, slots=True)
class CompactCardsOp:
    temp_id: str
    card_ids: list[str] = field(default_factory=list)
    memory: str = ""
    why: str = ""
    avoid: str = ""
    use_as: str = ""
    confidence: str = "medium"
    kind: str = "compact"


@dataclass(frozen=True, slots=True)
class CreateMemoryCardOp:
    temp_id: str
    memory: str = ""
    why: str = ""
    avoid: str = ""
    use_as: str = ""
    source_task_ids: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    risk_patterns: list[str] = field(default_factory=list)
    confidence: str = "medium"


@dataclass(frozen=True, slots=True)
class CreatePatternCardOp:
    temp_id: str
    memory: str = ""
    why: str = ""
    avoid: str = ""
    use_as: str = ""
    source_task_ids: list[str] = field(default_factory=list)
    task_types: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    risk_patterns: list[str] = field(default_factory=list)
    confidence: str = "medium"


Operation = (
    EditCardOp | ArchiveCardOp | RestoreCardOp
    | MergeCardsOp | CompactCardsOp | CreatePatternCardOp
    | CreateMemoryCardOp
)

OPERATION_TYPES: frozenset[str] = frozenset({
    "edit_card",
    "archive_card",
    "restore_archived_card",
    "merge_cards",
    "compact_cards",
    "create_pattern_card",
    "create_memory_card",
})


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None


def _str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def parse_operation(temp_id: str, payload: dict[str, Any]) -> Operation | None:
    """Map ``payload`` to the right operation dataclass.

    Returns ``None`` when the operation type is unknown or ``temp_id`` is empty.
    The operation type is read from ``payload["operation"]``; ``temp_id`` is the
    agent-assigned correlation id passed alongside the payload (so the backend
    can echo it back in the response).
    """
    if not isinstance(temp_id, str) or not temp_id:
        return None
    if not isinstance(payload, dict):
        return None
    op_type = payload.get("operation")
    if op_type == "edit_card":
        return EditCardOp(
            temp_id=temp_id,
            card_id=_str(payload.get("card_id")),
            memory=_opt_str(payload.get("memory")),
            why=_opt_str(payload.get("why")),
            avoid=_opt_str(payload.get("avoid")),
            use_as=_opt_str(payload.get("use_as")),
            confidence=_opt_str(payload.get("confidence")),
        )
    if op_type == "archive_card":
        return ArchiveCardOp(
            temp_id=temp_id,
            card_id=_str(payload.get("card_id")),
            reason=_str(payload.get("reason")),
        )
    if op_type == "restore_archived_card":
        return RestoreCardOp(
            temp_id=temp_id,
            card_id=_str(payload.get("card_id")),
            reason=_str(payload.get("reason")),
        )
    if op_type == "merge_cards":
        return MergeCardsOp(
            temp_id=temp_id,
            card_ids=_str_list(payload.get("card_ids")),
            memory=_str(payload.get("memory")),
            why=_str(payload.get("why")),
            avoid=_str(payload.get("avoid")),
            use_as=_str(payload.get("use_as")),
            confidence=_str(payload.get("confidence"), "medium") or "medium",
            kind="merge",
        )
    if op_type == "compact_cards":
        return CompactCardsOp(
            temp_id=temp_id,
            card_ids=_str_list(payload.get("card_ids")),
            memory=_str(payload.get("memory")),
            why=_str(payload.get("why")),
            avoid=_str(payload.get("avoid")),
            use_as=_str(payload.get("use_as")),
            confidence=_str(payload.get("confidence"), "medium") or "medium",
            kind="compact",
        )
    if op_type == "create_pattern_card":
        return CreatePatternCardOp(
            temp_id=temp_id,
            memory=_str(payload.get("memory")),
            why=_str(payload.get("why")),
            avoid=_str(payload.get("avoid")),
            use_as=_str(payload.get("use_as")),
            source_task_ids=_str_list(payload.get("source_task_ids")),
            task_types=_str_list(payload.get("task_types")),
            files=_str_list(payload.get("files")),
            modules=_str_list(payload.get("modules")),
            risk_patterns=_str_list(payload.get("risk_patterns")),
            confidence=_str(payload.get("confidence"), "medium") or "medium",
        )
    if op_type == "create_memory_card":
        return CreateMemoryCardOp(
            temp_id=temp_id,
            memory=_str(payload.get("memory")),
            why=_str(payload.get("why")),
            avoid=_str(payload.get("avoid")),
            use_as=_str(payload.get("use_as")),
            source_task_ids=_str_list(payload.get("source_task_ids")),
            task_types=_str_list(payload.get("task_types")),
            files=_str_list(payload.get("files")),
            modules=_str_list(payload.get("modules")),
            risk_patterns=_str_list(payload.get("risk_patterns")),
            confidence=_str(payload.get("confidence"), "medium") or "medium",
        )
    return None
