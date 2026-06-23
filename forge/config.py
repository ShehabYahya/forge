from __future__ import annotations

import json
import typing
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    w_agent: float = 0.35
    w_det: float = 0.65
    w_quality: float = 0.70
    w_relevance: float = 0.30
    min_history: int = 2
    exploration_slots: int = 2
    max_cards: int = 10
    max_chars: int = 4000


@dataclass(frozen=True, slots=True)
class MaintenanceReviewConfig:
    allow: tuple[str, ...] = (
        "start_task",
        "review_changes",
        "finish_task",
        "submit_outcome",
        "expand_tool_result",
        "apply_memory_review_batch",
        "get_maintenance_context",
        "finish_memory_maintenance",
        "read_active_cards",
        "read_archived_cards",
        "read_tasks",
        "read_telemetry",
    )
    deny: tuple[str, ...] = ("edit", "write", "bash")
    max_repair_attempts: int = 2
    pattern_min_source_tasks: int = 2
    high_rated_threshold: float = 0.7
    high_rated_min_observations: int = 5
    stale_days: int = 30


@dataclass(frozen=True, slots=True)
class NotificationsConfig:
    low_confidence_threshold: int = 5
    misleading_threshold: int = 3
    stale_days: int = 30
    one_per_session: bool = True


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    memory_min_chars: int = 40
    memory_max_chars: int = 400
    why_min_chars: int = 20
    generic_blocklist: tuple[str, ...] = (
        "be careful",
        "write tests",
        "keep it simple",
        "avoid bugs",
        "validate changes",
        "check everything",
        "follow best practices",
    )


@dataclass(frozen=True, slots=True)
class MaintenanceConfig:
    review: MaintenanceReviewConfig = field(default_factory=MaintenanceReviewConfig)


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    storage_root: str = "~/.forge/memory"
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    maintenance: MaintenanceConfig = field(default_factory=MaintenanceConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)

    @property
    def maintenance_review(self) -> MaintenanceReviewConfig:
        """Compatibility alias for pre-redesign JSON overrides and callers."""
        return self.maintenance.review


@dataclass(frozen=True, slots=True)
class ForgeConfig:
    memory: MemoryConfig = field(default_factory=MemoryConfig)


def default_config() -> ForgeConfig:
    """Return a ``ForgeConfig`` with all spec defaults."""
    return ForgeConfig()


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` over ``base`` (both dicts)."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _build(cls, data: dict):
    """Reconstruct a frozen dataclass ``cls`` from a (merged) dict.

    Nested dataclass fields are rebuilt recursively; list values for
    tuple-typed fields are coerced to tuples so the result stays
    consistent with the defaults. Unknown keys are ignored.
    """
    hints = typing.get_type_hints(cls)
    kwargs: dict = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        ftype = hints.get(f.name)
        if is_dataclass(ftype):
            if isinstance(value, dict):
                kwargs[f.name] = _build(ftype, value)
            # A non-dict for a nested section is treated as "no override".
            continue
        origin = typing.get_origin(ftype)
        if origin is tuple and isinstance(value, list):
            value = tuple(value)
        kwargs[f.name] = value
    return cls(**kwargs)


def load_config(runtime_root: Path | str | None = None) -> ForgeConfig:
    """Load ``{runtime_root}/config.json`` (or ``~/.forge/config.json``).

    The on-disk format is JSON. Any subset of values may be overridden; missing
    keys fall back to the spec defaults. Missing files, permission errors, and
    malformed JSON all return ``default_config()``. ``storage_root`` is stored
    verbatim (with ``~`` intact); callers expand it at use time.
    """
    if runtime_root is not None:
        path = Path(runtime_root).expanduser() / "config.json"
    else:
        path = Path.home() / ".forge" / "config.json"
        legacy_path = Path.home() / ".forge-alpha" / "config.json"
        if not path.exists() and legacy_path.exists():
            path = legacy_path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default_config()
    if not isinstance(raw, dict):
        return default_config()
    memory = raw.get("memory")
    if isinstance(memory, dict) and "maintenance_review" in memory and "maintenance" not in memory:
        raw = dict(raw)
        raw["memory"] = dict(memory)
        raw["memory"]["maintenance"] = {"review": raw["memory"].pop("maintenance_review")}
    merged = _deep_merge(asdict(default_config()), raw)
    return _build(ForgeConfig, merged)
