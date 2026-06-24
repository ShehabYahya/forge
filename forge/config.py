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


def _strip_jsonc_comments(text: str) -> str:
    """Remove ``//`` line comments and ``/* ... */`` block comments from JSONC text.

    Comments inside JSON string literals are preserved (e.g. the ``//`` in a URL
    like ``"https://example.com"`` is kept). Escaped quotes (``\\"``) inside
    strings are handled so a quote character inside a value does not end the
    string prematurely. The output is plain JSON suitable for ``json.loads``.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


_LAST_LOAD_WARNINGS: list[str] = []


def load_warnings() -> list[str]:
    """Return and clear the warnings produced by the most recent ``load_config`` call.

    Each entry is a human-readable, actionable string naming the path tried and
    the specific failure (missing file, permission denied, parse error, non-object
    JSON). An empty list means the config loaded cleanly.
    """
    warnings = list(_LAST_LOAD_WARNINGS)
    _LAST_LOAD_WARNINGS.clear()
    return warnings


def load_config(runtime_root: Path | str | None = None) -> ForgeConfig:
    """Load ``{runtime_root}/config.json`` (or ``~/.forge/config.json``).

    The on-disk format is JSON with optional JSONC-style comments (``//`` line
    comments and ``/* ... */`` block comments); comments are stripped before
    parsing. Any subset of values may be overridden; missing keys fall back to
    the spec defaults. Missing files, permission errors, and malformed JSON all
    return ``default_config()`` and record a warning accessible via
    :func:`load_warnings`. ``storage_root`` is stored verbatim (with ``~``
    intact); callers expand it at use time.
    """
    _LAST_LOAD_WARNINGS.clear()
    if runtime_root is not None:
        path = Path(runtime_root).expanduser() / "config.json"
    else:
        path = Path.home() / ".forge" / "config.json"
        legacy_path = Path.home() / ".forge-alpha" / "config.json"
        if not path.exists() and legacy_path.exists():
            path = legacy_path
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _LAST_LOAD_WARNINGS.append(
            f"config.json not found at {path}; using defaults"
        )
        return default_config()
    except PermissionError:
        _LAST_LOAD_WARNINGS.append(
            f"config.json at {path} could not be read (permission denied); using defaults"
        )
        return default_config()
    except OSError as exc:
        _LAST_LOAD_WARNINGS.append(
            f"config.json at {path} could not be read ({exc}); using defaults"
        )
        return default_config()
    try:
        raw = json.loads(_strip_jsonc_comments(text))
    except ValueError as exc:
        _LAST_LOAD_WARNINGS.append(
            f"config.json at {path} could not be parsed ({exc}); using defaults"
        )
        return default_config()
    if not isinstance(raw, dict):
        _LAST_LOAD_WARNINGS.append(
            f"config.json at {path} is valid JSON but not an object "
            f"(got {type(raw).__name__}); using defaults"
        )
        return default_config()
    memory = raw.get("memory")
    if isinstance(memory, dict) and "maintenance_review" in memory and "maintenance" not in memory:
        raw = dict(raw)
        raw["memory"] = dict(memory)
        raw["memory"]["maintenance"] = {"review": raw["memory"].pop("maintenance_review")}
    merged = _deep_merge(asdict(default_config()), raw)
    return _build(ForgeConfig, merged)


def generate_commented_config() -> str:
    """Return a fully-commented JSONC config string with every Forge setting.

    Each setting carries a plain-English ``//`` comment and the spec default
    value. After comment-stripping the result parses to exactly
    ``default_config()``. Intended for the ``forge config init`` command so a
    non-technical user can edit one file to adjust Forge's behavior.
    """
    return _COMMENTED_CONFIG


_COMMENTED_CONFIG = """{
  // ============================================================
  //  Forge configuration
  //  Edit the values below to adjust how Forge behaves.
  //  Lines starting with // are comments and are ignored.
  //  Delete a value to go back to its default.
  // ============================================================

  // "memory" controls Forge's long-term memory cards and maintenance.
  "memory": {
    // Where Forge stores its memory cards and logs on disk.
    // ~ means your home directory, so ~/.forge/memory is the default.
    "storage_root": "~/.forge/memory",

    // --- Scoring: how Forge decides which memory cards to show an agent ---
    "scoring": {
      // How much weight to give the agent's own self-rating of a card (0.0 to 1.0).
      "w_agent": 0.35,
      // How much weight to give deterministic signals, like past task outcomes (0.0 to 1.0).
      "w_det": 0.65,
      // Weight for a card's quality score (0.0 to 1.0).
      "w_quality": 0.70,
      // Weight for how relevant a card is to the current task (0.0 to 1.0).
      "w_relevance": 0.30,
      // Minimum number of past task outcomes needed before scoring trusts history.
      "min_history": 2,
      // Number of "exploration" slots that may show less-proven cards so Forge can learn.
      "exploration_slots": 2,
      // Maximum number of memory cards injected into a single task at once.
      "max_cards": 10,
      // Maximum total characters of memory text injected into a single task.
      "max_chars": 4000
    },

    // --- Maintenance: the self-review flow for cleaning up memory ---
    "maintenance": {
      "review": {
        // Tool operations the maintenance session is allowed to use.
        "allow": [
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
          "read_telemetry"
        ],
        // Tools blocked during a maintenance session so it cannot edit files or run commands.
        "deny": [
          "edit",
          "write",
          "bash"
        ],
        // How many times the maintenance agent may attempt to repair a single card.
        "max_repair_attempts": 2,
        // Minimum number of source tasks needed before a "cross-task pattern" card can be created.
        "pattern_min_source_tasks": 2,
        // Score (0.0 to 1.0) at or above which a card is considered "highly rated".
        "high_rated_threshold": 0.7,
        // Minimum number of helpful ratings needed to count a card as highly rated.
        "high_rated_min_observations": 5,
        // Days without review after which a memory card is considered stale.
        "stale_days": 30
      }
    },

    // --- Notifications: when Forge suggests you run a memory review ---
    "notifications": {
      // Suggest a review when at least this many cards have low-confidence (unverified) claims.
      "low_confidence_threshold": 5,
      // Suggest a review when at least this many cards were rated "misleading" in feedback.
      "misleading_threshold": 3,
      // Days after which an unreviewed card counts toward a stale-card notification.
      "stale_days": 30,
      // Only show the "review memory" notification once per session (true or false).
      "one_per_session": true
    },

    // --- Validation: rules every memory card must satisfy ---
    "validation": {
      // Minimum number of characters required in a card's "memory" text.
      "memory_min_chars": 40,
      // Maximum number of characters allowed in a card's "memory" text.
      "memory_max_chars": 400,
      // Minimum number of characters required in a card's "why" explanation.
      "why_min_chars": 20,
      // Phrases that are too generic to be useful; cards containing them are rejected.
      "generic_blocklist": [
        "be careful",
        "write tests",
        "keep it simple",
        "avoid bugs",
        "validate changes",
        "check everything",
        "follow best practices"
      ]
    }
  }
}
"""
