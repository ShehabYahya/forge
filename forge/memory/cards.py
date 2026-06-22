from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


ENTRY_TYPES: tuple[str, ...] = (
    "validation_memory",
    "pitfall_memory",
    "cross_task_pattern",
)
TRANSFERABILITY: tuple[str, ...] = ("local_only", "transferable")
CONFIDENCE: tuple[str, ...] = ("high", "medium", "low")


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


@dataclass(frozen=True, slots=True)
class AppliesWhen:
    task_types: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    risk_patterns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("task_types", "files", "modules", "risk_patterns"):
            if not _is_str_list(getattr(self, name)):
                raise ValueError(f"applies_when.{name} must be a list of strings")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "AppliesWhen":
        if not value:
            return cls()
        return cls(
            task_types=list(value.get("task_types") or []),
            files=list(value.get("files") or []),
            modules=list(value.get("modules") or []),
            risk_patterns=list(value.get("risk_patterns") or []),
        )


@dataclass(frozen=True, slots=True)
class MemoryCard:
    card_id: str
    memory: str
    why: str
    avoid: str
    use_as: str
    entry_type: str
    transferability: str
    source_repo_root: str
    source_repo_id: str
    applies_when: AppliesWhen
    confidence: str
    source_task_ids: list[str]
    supersedes: list[str]
    superseded_by: str | None
    created_at: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.card_id, str):
            raise ValueError("card_id must be a string")
        if not isinstance(self.memory, str) or not self.memory.strip():
            raise ValueError("memory must be a non-empty string")
        if not isinstance(self.why, str):
            raise ValueError("why must be a string")
        if not isinstance(self.avoid, str):
            raise ValueError("avoid must be a string")
        if not isinstance(self.use_as, str):
            raise ValueError("use_as must be a string")
        if self.entry_type not in ENTRY_TYPES:
            raise ValueError(f"entry_type must be one of {ENTRY_TYPES}")
        if self.transferability not in TRANSFERABILITY:
            raise ValueError(f"transferability must be one of {TRANSFERABILITY}")
        if not isinstance(self.source_repo_root, str):
            raise ValueError("source_repo_root must be a string")
        if not isinstance(self.source_repo_id, str):
            raise ValueError("source_repo_id must be a string")
        if not isinstance(self.applies_when, AppliesWhen):
            raise ValueError("applies_when must be an AppliesWhen instance")
        if self.confidence not in CONFIDENCE:
            raise ValueError(f"confidence must be one of {CONFIDENCE}")
        if not _is_str_list(self.source_task_ids):
            raise ValueError("source_task_ids must be a list of strings")
        if not _is_str_list(self.supersedes):
            raise ValueError("supersedes must be a list of strings")
        if self.superseded_by is not None and not isinstance(self.superseded_by, str):
            raise ValueError("superseded_by must be a string or None")
        if self.schema_version != 1:
            raise ValueError("unsupported memory card schema_version")
        datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryCard":
        return cls(
            card_id=value["card_id"],
            memory=value["memory"],
            why=value.get("why", ""),
            avoid=value.get("avoid", ""),
            use_as=value.get("use_as", ""),
            entry_type=value["entry_type"],
            transferability=value["transferability"],
            source_repo_root=value["source_repo_root"],
            source_repo_id=value["source_repo_id"],
            applies_when=AppliesWhen.from_dict(value.get("applies_when")),
            confidence=value["confidence"],
            source_task_ids=list(value.get("source_task_ids") or []),
            supersedes=list(value.get("supersedes") or []),
            superseded_by=value.get("superseded_by"),
            created_at=value["created_at"],
            schema_version=value.get("schema_version", 1),
        )
