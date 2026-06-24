from __future__ import annotations

from forge.config import ValidationConfig, default_config
from forge.memory.validation import (
    has_concrete_anchor,
    is_generic_only,
    normalize_memory_text,
    validate_memory_text,
    validate_why,
)


def _cfg() -> ValidationConfig:
    return default_config().memory.validation


def test_valid_memory_with_anchor_passes():
    memory = (
        "When calling load_config() in forge/config.py, always pass "
        "runtime_root to override the home directory path."
    )
    assert validate_memory_text(memory, _cfg()) is None


def test_memory_too_short_fails():
    memory = "too short to be a valid memory"
    assert len(memory) < 40
    reason = validate_memory_text(memory, _cfg())
    assert reason is not None
    assert "at least 40" in reason


def test_memory_too_long_fails():
    memory = "x" * 601
    reason = validate_memory_text(memory, _cfg())
    assert reason is not None
    assert "at most 600" in reason


def test_memory_at_min_boundary_passes():
    memory = "be careful when editing forge/service.py"
    assert len(memory) == 40
    # Matches blocklist "be careful" but has a concrete anchor -> valid.
    assert validate_memory_text(memory, _cfg()) is None


def test_memory_at_max_boundary_passes():
    memory = "a" * 591 + " forge.py"
    assert len(memory) == 600
    assert validate_memory_text(memory, _cfg()) is None


def test_generic_only_memory_rejected():
    memory = "be careful when writing code, keep it simple and avoid bugs always"
    assert len(memory) >= 40
    assert is_generic_only(memory, _cfg()) is True
    reason = validate_memory_text(memory, _cfg())
    assert reason is not None
    assert "too generic" in reason
    assert "be careful" in reason


def test_generic_text_with_anchor_not_generic_only():
    memory = "be careful when editing forge/service.py to avoid bugs"
    assert is_generic_only(memory, _cfg()) is False
    assert validate_memory_text(memory, _cfg()) is None


def test_non_blocklist_short_memory_fails_on_length_only():
    # Long enough but still well under max; no blocklist; has anchor -> valid.
    memory = "Running pytest with the -x flag stops on the first failing test case."
    assert validate_memory_text(memory, _cfg()) is None


def test_has_concrete_anchor_detects_each_anchor_kind():
    assert has_concrete_anchor("edit forge/config.py") is True      # file path
    assert has_concrete_anchor("see src/index") is True             # slash path
    assert has_concrete_anchor("call load_config()") is True        # function call
    assert has_concrete_anchor("define def helper here") is True    # def token
    assert has_concrete_anchor("use `MemoryStore`") is True         # backtick
    assert has_concrete_anchor("use MemoryStore") is True           # CamelCase
    assert has_concrete_anchor("the snake_case token") is True      # snake_case
    assert has_concrete_anchor("run pytest") is True                # tool keyword
    assert has_concrete_anchor("no anchor here just plain words") is False
    assert has_concrete_anchor("") is False
    assert has_concrete_anchor("a_b") is False  # snake_case but length 3 < 4


def test_is_generic_only_without_blocklist_match_is_false():
    # No blocklist phrase -> not generic-only regardless of anchors.
    assert is_generic_only("a perfectly specific note about forge/config.py", _cfg()) is False


def test_is_generic_only_empty_or_non_string_is_false():
    assert is_generic_only("", _cfg()) is False
    assert is_generic_only(None, _cfg()) is False  # type: ignore[arg-type]


def test_validate_why_none_and_empty_are_valid():
    assert validate_why(None, _cfg()) is None
    assert validate_why("", _cfg()) is None
    assert validate_why("   ", _cfg()) is None


def test_validate_why_short_fails():
    reason = validate_why("short", _cfg())
    assert reason is not None
    assert "at least 20" in reason


def test_validate_why_long_enough_passes():
    why = "this is a long enough why reason text"
    assert len(why) >= 20
    assert validate_why(why, _cfg()) is None


def test_validate_why_non_string_fails():
    reason = validate_why(123, _cfg())  # type: ignore[arg-type]
    assert reason is not None
    assert "string" in reason


def test_normalize_memory_text_lowercases_and_collapses_whitespace():
    assert normalize_memory_text("  Foo   Bar  ") == "foo bar"
    assert normalize_memory_text("FOO\n\tBAR  baz") == "foo bar baz"
    assert normalize_memory_text("already clean") == "already clean"
    assert normalize_memory_text("   ") == ""
    assert normalize_memory_text("") == ""
    assert normalize_memory_text(None) == ""  # type: ignore[arg-type]


def test_non_string_memory_rejected():
    assert validate_memory_text(None, _cfg()) is not None  # type: ignore[arg-type]
    assert validate_memory_text(123, _cfg()) is not None  # type: ignore[arg-type]


def test_validation_driven_by_config_thresholds():
    # A custom config with a higher min proves thresholds come from config.
    custom = ValidationConfig(
        memory_min_chars=50,
        memory_max_chars=100,
        why_min_chars=10,
        generic_blocklist=("be careful",),
    )
    # 45 chars -> under custom min (50) but over default min (40).
    memory = "x" * 45
    assert validate_memory_text(memory, _cfg()) is None  # default allows 45
    assert validate_memory_text(memory, custom) is not None  # custom rejects 45
    # why of 12 chars: under default min (20) but over custom min (10).
    why = "y" * 12
    assert validate_why(why, _cfg()) is not None
    assert validate_why(why, custom) is None
