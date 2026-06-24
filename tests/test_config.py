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
    _strip_jsonc_comments,
    default_config,
    generate_commented_config,
    load_config,
    load_warnings,
)


def test_defaults_match_spec_values():
    cfg = default_config()
    assert isinstance(cfg, ForgeConfig)

    mem = cfg.memory
    assert mem.storage_root == "~/.forge/memory"

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
        "read",
        "grep",
        "glob",
    )
    assert mr.deny == ("edit", "write", "bash")
    assert mr.max_repair_attempts == 2
    assert mr.pattern_min_source_tasks == 2
    assert mr.high_rated_threshold == 0.7
    assert mr.high_rated_min_observations == 5
    assert mr.stale_days == 30
    assert mr.session_lock_ttl_seconds == 3600
    assert mr.session_lock_force_enabled is True

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
        "read",
        "grep",
        "glob",
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
    (tmp_path / ".forge").mkdir()
    (tmp_path / ".forge" / "config.json").write_text(
        json.dumps({"memory": {"scoring": {"max_cards": 3}}}),
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.memory.scoring.max_cards == 3


def test_load_config_runtime_root_none_accepts_legacy_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".forge-alpha").mkdir()
    (tmp_path / ".forge-alpha" / "config.json").write_text(
        json.dumps({"memory": {"scoring": {"max_cards": 4}}}),
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.memory.scoring.max_cards == 4


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


# --------------------------------------------------------------------------- #
#  FIX #5: config load warnings
# --------------------------------------------------------------------------- #


def test_load_config_malformed_json_produces_warning(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_config(tmp_path) == default_config()
    warnings = load_warnings()
    assert len(warnings) == 1
    assert "config.json" in warnings[0]
    assert str(path) in warnings[0]
    assert "parsed" in warnings[0] or "parse" in warnings[0]


def test_load_config_non_dict_json_produces_warning(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert load_config(tmp_path) == default_config()
    warnings = load_warnings()
    assert len(warnings) == 1
    assert str(path) in warnings[0]
    assert "not an object" in warnings[0]


def test_load_config_missing_file_produces_warning(tmp_path):
    path = tmp_path / "config.json"
    assert load_config(tmp_path) == default_config()
    warnings = load_warnings()
    assert len(warnings) == 1
    assert str(path) in warnings[0]
    assert "not found" in warnings[0]


def test_load_config_valid_config_produces_no_warning(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"memory": {"scoring": {"max_cards": 5}}}),
        encoding="utf-8",
    )
    assert load_config(tmp_path).memory.scoring.max_cards == 5
    assert load_warnings() == []


def test_load_warnings_returns_and_clears(tmp_path):
    (tmp_path / "config.json").write_text("{bad json", encoding="utf-8")
    load_config(tmp_path)
    first = load_warnings()
    assert first  # non-empty
    second = load_warnings()
    assert second == []  # cleared


def test_forgeservice_surfaces_config_warnings_in_start_task(repo, tmp_path):
    from forge.service import ForgeService

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "config.json").write_text("{not valid json", encoding="utf-8")

    counter = iter(range(1000))
    svc = ForgeService(runtime, clock=lambda: float(next(counter)),
                       id_factory=lambda seed: "task_cfg_warn")
    assert svc.config_warnings  # captured at construction

    result = svc.start_task("implement feature", str(repo), host_session_id="cfgwarn")
    assert result["ok"] is True
    warnings = result["warnings"]
    assert any("config.json" in w and ("parsed" in w or "parse" in w) for w in warnings), warnings
    # Surfaced once and consumed: a second start_task must not repeat the warning.
    result2 = svc.start_task("another feature", str(repo), host_session_id="cfgwarn")
    assert not any("config.json" in w for w in result2["warnings"]), result2["warnings"]


# --------------------------------------------------------------------------- #
#  FEATURE: JSONC comment stripping
# --------------------------------------------------------------------------- #


def test_strip_jsonc_preserves_url_in_string():
    text = '{"url": "https://example.com/page"}'
    assert _strip_jsonc_comments(text) == text


def test_strip_jsonc_removes_line_comment_after_value():
    text = '{"a": 1 // a comment\n}'
    assert _strip_jsonc_comments(text) == '{"a": 1 \n}'


def test_strip_jsonc_removes_block_comment():
    text = '{"a": 1 /* a block comment */}'
    assert _strip_jsonc_comments(text) == '{"a": 1 }'


def test_strip_jsonc_removes_full_line_comment():
    text = '// top comment\n{"a": 1}'
    assert _strip_jsonc_comments(text) == '\n{"a": 1}'


def test_strip_jsonc_preserves_double_slash_inside_string():
    text = '{"a": "//not a comment"}'
    assert _strip_jsonc_comments(text) == text


def test_strip_jsonc_preserves_escaped_quote_in_string():
    # The // after an escaped quote must stay (we are still inside the string).
    text = '{"a": "say \\"hi\\" // keep"}'
    assert _strip_jsonc_comments(text) == text


def test_strip_jsonc_mixed_cases():
    text = (
        '// header\n'
        '{\n'
        '  "url": "https://x.com", // trailing\n'
        '  /* block */ "n": 2\n'
        '}'
    )
    stripped = _strip_jsonc_comments(text)
    assert "https://x.com" in stripped
    assert "header" not in stripped
    assert "trailing" not in stripped
    assert "block" not in stripped
    # And it is valid JSON.
    assert json.loads(stripped) == {"url": "https://x.com", "n": 2}


def test_strip_jsonc_idempotent_on_plain_json():
    text = json.dumps({"a": 1, "b": [1, 2, 3], "c": "https://x.com"})
    assert _strip_jsonc_comments(text) == text


# --------------------------------------------------------------------------- #
#  FEATURE: commented config file + `forge config init`
# --------------------------------------------------------------------------- #


def test_generate_commented_config_round_trips_to_defaults(tmp_path):
    text = generate_commented_config()
    (tmp_path / "config.json").write_text(text, encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg == default_config()
    assert load_warnings() == []


def test_config_init_writes_commented_defaults(monkeypatch, tmp_path):
    from forge.cli import main

    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    main(["config", "init"])

    config_path = tmp_path / "config.json"
    assert config_path.exists()
    # The written file still contains comments (JSONC).
    raw = config_path.read_text(encoding="utf-8")
    assert "//" in raw
    # After loading (which strips comments) it equals the spec defaults.
    assert load_config(tmp_path) == default_config()
    assert load_warnings() == []


def test_config_init_refuses_overwrite_without_force(monkeypatch, tmp_path):
    from forge.cli import main

    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    main(["config", "init"])
    config_path = tmp_path / "config.json"
    original = config_path.read_text(encoding="utf-8")

    # Hand-edit the file (simulating a user customizing it).
    edited = original.replace('"max_cards": 10', '"max_cards": 3')
    config_path.write_text(edited, encoding="utf-8")

    main(["config", "init"])  # no --force
    assert config_path.read_text(encoding="utf-8") == edited  # unchanged
    assert load_config(tmp_path).memory.scoring.max_cards == 3


def test_config_init_overwrites_with_force(monkeypatch, tmp_path):
    from forge.cli import main

    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    main(["config", "init"])
    config_path = tmp_path / "config.json"
    config_path.write_text("{bad", encoding="utf-8")  # corrupt it

    main(["config", "init", "--force"])
    # Restored to a valid commented config that loads to defaults.
    assert load_config(tmp_path) == default_config()
    assert load_warnings() == []


def test_edited_commented_file_loads_override(tmp_path):
    text = generate_commented_config()
    # A user edits one value inside the commented file (comment kept on its line).
    edited = text.replace('"max_cards": 10', '"max_cards": 4')
    (tmp_path / "config.json").write_text(edited, encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.memory.scoring.max_cards == 4
    # Everything else stays at defaults.
    assert cfg.memory.scoring.w_agent == 0.35
    assert cfg.memory.notifications.one_per_session is True
    assert load_warnings() == []
