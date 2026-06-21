from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryCard:
    card_id: str
    memory: str
    repo_id: str
    created_at: str
    schema_version: int = 1
    why: str | None = None
    avoid: str | None = None
    use_as: str | None = None
    task_keywords: list[str] = field(default_factory=list)
    file_patterns: list[str] = field(default_factory=list)
    risk_patterns: list[str] = field(default_factory=list)
    priority: int = 0
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.card_id.strip() or not self.memory.strip() or not self.repo_id.strip():
            raise ValueError("card_id, memory, and repo_id must be non-empty")
        if self.schema_version != 1:
            raise ValueError("unsupported memory card schema_version")
        if not -10 <= self.priority <= 10:
            raise ValueError("priority must be between -10 and 10")
        datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        for values in (self.task_keywords, self.file_patterns, self.risk_patterns):
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError("pattern fields must be string lists")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryCard":
        fields = cls.__dataclass_fields__
        return cls(**{key: value[key] for key in fields if key in value})

