from __future__ import annotations

import dataclasses
import json

import pytest

from forge.config import (
    ForgeConfig,
    MaintenanceConfig,
    MaintenanceReviewConfig,
    MemoryConfig,
    NotificationsConfig,
    ScoringConfig,
    ValidationConfig,
    default_config,
    load_config,
)


def test_defaults_match_spec_values():
    cfg = default_config()
    assert isinstance(cfg, ForgeConfig)

    mem = cfg.memory
    assert mem.storage_root == "~/.forge-alpha/memory"

    s = mem.scoring
    assert s.w_agent == 0.35
    assert s.w_det == 0.65
    assert s.w_quality == 0.70
    assert s.w_relevance == 0.30
    assert s.min_history == 2
    assert s.exploration_slots == 2
    assert s.max_cards == 10
    assert s.max_chars == 4000

    assert isinstance(mem.maintenance, MaintenanceConfig)
    mr = mem.maintenance.review
    assert mr.allow == (
        "forge_start_task",
        "forge_review_changes",
        "forge_finish_task",
        "forge_submit_outcome",
        "forge_expand_tool_result",
        "apply_memory_review_batch",
        "get_maintenance_context",
        "finish_memory_maintenance",
        "read_active_cards",
        "read_archived_cards",
        "read_tasks",
        "read_telemetry",
    )
    assert mr.deny == ("edit", "write", "bash")
    assert mr.max_repair_attempts == 2
    assert mr.pattern_min_source_tasks == 2
    assert mr.high_rated_threshold == 0.7
    assert mr.high_rated_min_observations == 5
    assert mr.stale_days == 30

    n = mem.notifications
    assert n.low_confidence_threshold == 5
    assert n.misleading_threshold == 3
    assert n.stale_days == 30
    assert n.one_per_session is True

    v = mem.validation
    assert v.memory_min_chars == 40
    assert v.memory_max_chars == 400
    assert v.why_min_chars == 20
    assert v.generic_blocklist == (
        "be careful",
        "write tests",
        "keep it simple",
        "avoid bugs",
        "validate changes",
        "check everything",
        "follow best practices",
    )


def test_dataclasses_are_frozen():
    cfg = default_config()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.memory.scoring.w_agent = 1.0  # type: ignore[misc]


def test_list_typed_fields_are_tuples():
    cfg = default_config()
    assert isinstance(cfg.memory.maintenance_review.allow, tuple)
    assert isinstance(cfg.memory.maintenance_review.deny, tuple)
    assert isinstance(cfg.memory.validation.generic_blocklist, tuple)


def test_default_config_returns_fresh_instance():
    assert default_config() == default_config()
    assert default_config() is not default_config()


def test_load_config_missing_file_returns_defaults(tmp_path):
    assert load_config(tmp_path) == default_config()


def test_load_config_accepts_string_runtime_root(tmp_path):
    assert load_config(str(tmp_path)) == default_config()


def test_load_config_partial_override_merges(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"memory": {"scoring": {"max_cards": 5}}}),
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.memory.scoring.max_cards == 5
    # Other scoring values keep defaults.
    assert cfg.memory.scoring.w_agent == 0.35
    assert cfg.memory.scoring.w_det == 0.65
    assert cfg.memory.scoring.max_chars == 4000
    assert cfg.memory.scoring.min_history == 2
    # Other sections keep defaults.
    assert cfg.memory.validation.memory_min_chars == 40
    assert cfg.memory.validation.generic_blocklist == (
        "be careful",
        "write tests",
        "keep it simple",
        "avoid bugs",
        "validate changes",
        "check everything",
        "follow best practices",
    )
    assert cfg.memory.notifications.low_confidence_threshold == 5
    assert cfg.memory.maintenance_review.max_repair_attempts == 2


def test_load_config_malformed_json_returns_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_config(tmp_path) == default_config()


def test_load_config_non_dict_json_returns_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    assert load_config(tmp_path) == default_config()


def test_load_config_full_override(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "memory": {
                    "storage_root": "~/custom/memory",
                    "scoring": {
                        "w_agent": 0.5,
                        "w_det": 0.5,
                        "w_quality": 0.6,
                        "w_relevance": 0.4,
                        "min_history": 3,
                        "exploration_slots": 1,
                        "max_cards": 7,
                        "max_chars": 3000,
                    },
                    "maintenance_review": {
                        "max_repair_attempts": 4,
                        "stale_days": 60,
                    },
                    "notifications": {
                        "low_confidence_threshold": 8,
                        "one_per_session": False,
                    },
                    "validation": {
                        "memory_min_chars": 50,
                        "generic_blocklist": ["be careful", "write tests"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.memory.storage_root == "~/custom/memory"
    assert cfg.memory.scoring.w_agent == 0.5
    assert cfg.memory.scoring.w_det == 0.5
    assert cfg.memory.scoring.max_cards == 7
    assert cfg.memory.scoring.min_history == 3
    # Non-overridden maintenance_review fields keep defaults.
    assert cfg.memory.maintenance_review.max_repair_attempts == 4
    assert cfg.memory.maintenance_review.stale_days == 60
    assert cfg.memory.maintenance_review.high_rated_threshold == 0.7
    assert cfg.memory.maintenance_review.allow == (
        "forge_start_task",
        "forge_review_changes",
        "forge_finish_task",
        "forge_submit_outcome",
        "forge_expand_tool_result",
        "apply_memory_review_batch",
        "get_maintenance_context",
        "finish_memory_maintenance",
        "read_active_cards",
        "read_archived_cards",
        "read_tasks",
        "read_telemetry",
    )
    assert cfg.memory.notifications.low_confidence_threshold == 8
    assert cfg.memory.notifications.one_per_session is False
    assert cfg.memory.notifications.misleading_threshold == 3  # default
    assert cfg.memory.validation.memory_min_chars == 50
    assert cfg.memory.validation.generic_blocklist == ("be careful", "write tests")
    assert cfg.memory.validation.memory_max_chars == 400  # default


def test_load_config_preserves_tilde_in_storage_root(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"memory": {"storage_root": "~/x/memory"}}),
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.memory.storage_root == "~/x/memory"


def test_load_config_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"memory": {"scoring": {"max_cards": 9}, "unknown": 1}, "extra": 2}),
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.memory.scoring.max_cards == 9
    assert cfg == load_config(tmp_path)  # stable


def test_load_config_runtime_root_none_uses_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert load_config() == default_config()
    (tmp_path / ".forge-alpha").mkdir()
    (tmp_path / ".forge-alpha" / "config.json").write_text(
        json.dumps({"memory": {"scoring": {"max_cards": 3}}}),
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.memory.scoring.max_cards == 3


def test_nested_config_types():
    cfg = default_config()
    assert isinstance(cfg.memory, MemoryConfig)
    assert isinstance(cfg.memory.scoring, ScoringConfig)
    assert isinstance(cfg.memory.maintenance, MaintenanceConfig)
    assert isinstance(cfg.memory.maintenance_review, MaintenanceReviewConfig)
    assert cfg.memory.maintenance_review is cfg.memory.maintenance.review
    assert isinstance(cfg.memory.notifications, NotificationsConfig)
    assert isinstance(cfg.memory.validation, ValidationConfig)


def test_load_config_accepts_nested_maintenance_review(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"memory": {"maintenance": {"review": {"stale_days": 45}}}}),
        encoding="utf-8",
    )
    assert load_config(tmp_path).memory.maintenance.review.stale_days == 45
