from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from forge.config import default_config
from forge.memory.card_factory import (
    classify_task_types,
    create_card_from_draft,
    derive_confidence,
    derive_modules,
    is_repo_specific,
)
from forge.memory.store import MemoryStore


# --------------------------------------------------------------------------- fixtures


def _clock() -> Callable[[], float]:
    counter = iter(range(1000))
    return lambda: float(next(counter))


def make_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory" / "cards.jsonl", clock=_clock())


def make_task(task_id: str = "task_1", repo_root: str = "/repo/alpha",
              task_text: str = "Fix the bug in forge/service.py") -> Any:
    return SimpleNamespace(task_id=task_id, repo_root=repo_root, task_text=task_text)


def make_review(passed: bool = True, changed_files: list[str] | None = None,
                blockers: list[str] | None = None) -> dict:
    return {
        "passed": passed,
        "changed_files": changed_files if changed_files is not None else ["forge/service.py"],
        "blockers": blockers if blockers is not None else [],
    }


VALID_MEMORY = (
    "When editing forge/service.py, pass runtime_root to load_config() so the "
    "home directory is not hardcoded for tests."
)
VALID_WHY = "past regressions in this module missed the override path"


# --------------------------------------------------------------------------- no draft


def test_no_draft_returns_ok_and_creates_no_card(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = create_card_from_draft(
        make_task(), make_review(), ("reported_passed", "unverified"),
        None, store, default_config(), "2026-01-01T00:00:00Z",
    )
    assert result == {"ok": True}
    assert result.get("warning") is None
    assert result.get("card") is None
    assert store.read_active() == []


# --------------------------------------------------------------------------- valid draft


def test_valid_draft_creates_card_with_backend_fields(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    task = make_task(task_id="task_42", task_text="Fix the bug in forge/service.py")
    review = make_review(passed=True, changed_files=["forge/service.py", "forge/config.py"])
    draft = {"memory": VALID_MEMORY, "why": VALID_WHY, "avoid": "hardcoding paths"}

    result = create_card_from_draft(
        task, review, ("reported_passed", "unverified"),
        draft, store, default_config(), "2026-01-01T00:00:00Z",
    )

    assert result["ok"] is True
    card = result["card"]
    assert card is not None
    # Backend-filled identity fields.
    assert card.card_id == "mem_000001"
    assert card.source_task_ids == ["task_42"]
    assert card.supersedes == []
    assert card.superseded_by is None
    assert card.created_at == "2026-01-01T00:00:00Z"
    assert card.schema_version == 1
    # Agent-provided text fields preserved.
    assert card.memory == VALID_MEMORY
    assert card.why == VALID_WHY
    assert card.avoid == "hardcoding paths"
    # use_as is always empty at creation (only edit_card fills it).
    assert card.use_as == ""
    # entry_type: success -> validation_memory.
    assert card.entry_type == "validation_memory"
    # source_repo_* come from the task.
    assert card.source_repo_root == "/repo/alpha"
    assert card.source_repo_id == "/repo/alpha"
    # unverified + passed -> medium.
    assert card.confidence == "medium"
    # applies_when.files mirrors review.changed_files.
    assert card.applies_when.files == ["forge/service.py", "forge/config.py"]
    # modules are top-level dir names of changed_files.
    assert card.applies_when.modules == ["forge"]
    # task_types from keyword classification of task_text.
    assert card.applies_when.task_types == ["bugfix"]
    # repo-specific files -> local_only.
    assert card.transferability == "local_only"
    # Card persisted.
    assert [c.card_id for c in store.read_active()] == ["mem_000001"]


def test_use_as_is_always_empty_at_creation_even_if_draft_provides_it(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    # The draft MUST NOT carry use_as; if it did, the factory still ignores it.
    draft = {"memory": VALID_MEMORY, "why": VALID_WHY, "use_as": "should be ignored"}
    result = create_card_from_draft(
        make_task(), make_review(), ("reported_passed", "unverified"),
        draft, store, default_config(), "2026-01-01T00:00:00Z",
    )
    assert result["card"].use_as == ""


# --------------------------------------------------------------------------- generic / validation


def test_generic_only_draft_rejected_no_card(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    generic = "be careful when writing code, keep it simple and avoid bugs always"
    assert len(generic) >= 40
    result = create_card_from_draft(
        make_task(), make_review(), ("reported_passed", "unverified"),
        {"memory": generic}, store, default_config(), "2026-01-01T00:00:00Z",
    )
    assert result["ok"] is True
    assert "card" not in result
    assert "rejected" in result["warning"]
    assert store.read_active() == []


def test_draft_too_short_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    short = "too short"
    assert len(short) < 40
    result = create_card_from_draft(
        make_task(), make_review(), ("reported_passed", "unverified"),
        {"memory": short}, store, default_config(), "2026-01-01T00:00:00Z",
    )
    assert result["ok"] is True
    assert "card" not in result
    assert "rejected" in result["warning"]
    assert "at least 40" in result["warning"]
    assert store.read_active() == []


def test_draft_why_too_short_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = create_card_from_draft(
        make_task(), make_review(), ("reported_passed", "unverified"),
        {"memory": VALID_MEMORY, "why": "short"}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    assert result["ok"] is True
    assert "card" not in result
    assert "rejected" in result["warning"]
    assert "at least 20" in result["warning"]
    assert store.read_active() == []


def test_draft_memory_missing_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = create_card_from_draft(
        make_task(), make_review(), ("reported_passed", "unverified"),
        {"why": VALID_WHY}, store, default_config(), "2026-01-01T00:00:00Z",
    )
    assert result["ok"] is True
    assert "card" not in result
    assert "rejected" in result["warning"]
    assert store.read_active() == []


# --------------------------------------------------------------------------- mismatch


def test_mismatch_honesty_creates_no_card(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = create_card_from_draft(
        make_task(), make_review(), ("reported_failed", "mismatch"),
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    assert result["ok"] is True
    assert "card" not in result
    assert "contradicts evidence" in result["warning"]
    assert store.read_active() == []


def test_mismatch_takes_priority_over_invalid_memory(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    # Both mismatch AND too-short memory. Mismatch must win so the warning
    # names the real reason (the claim contradicts the evidence).
    result = create_card_from_draft(
        make_task(), make_review(), ("reported_failed", "mismatch"),
        {"memory": "too short"}, store, default_config(), "2026-01-01T00:00:00Z",
    )
    assert "card" not in result
    assert "contradicts evidence" in result["warning"]


# --------------------------------------------------------------------------- pitfall


def test_pitfall_with_corroborating_blockers_is_medium(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    review = make_review(passed=False, changed_files=["forge/service.py"],
                         blockers=["Python syntax error in forge/service.py"])
    result = create_card_from_draft(
        make_task(task_text="Fix the bug in forge/service.py"), review,
        ("not_run", "honest_failure"),
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    card = result["card"]
    assert card.entry_type == "pitfall_memory"
    assert card.confidence == "medium"
    # risk_patterns derived from blockers when draft omits them.
    assert card.applies_when.risk_patterns == ["Python syntax error in forge/service.py"]


def test_pitfall_without_blockers_is_low(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    review = make_review(passed=False, changed_files=["forge/service.py"], blockers=[])
    result = create_card_from_draft(
        make_task(), review, ("not_run", "honest_failure"),
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    card = result["card"]
    assert card.entry_type == "pitfall_memory"
    assert card.confidence == "low"
    assert card.applies_when.risk_patterns == []


def test_pitfall_with_no_review_is_low(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    result = create_card_from_draft(
        make_task(), None, ("not_run", "honest_failure"),
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    card = result["card"]
    assert card.entry_type == "pitfall_memory"
    assert card.confidence == "low"
    assert card.applies_when.files == []
    assert card.transferability == "transferable"  # no files -> transferable


# --------------------------------------------------------------------------- risk_patterns source


def test_draft_risk_patterns_override_blockers(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    review = make_review(blockers=["blocker from review"])
    draft = {"memory": VALID_MEMORY, "why": VALID_WHY,
             "risk_patterns": ["scope drift", "unbounded edit"]}
    result = create_card_from_draft(
        make_task(), review, ("reported_passed", "unverified"),
        draft, store, default_config(), "2026-01-01T00:00:00Z",
    )
    card = result["card"]
    assert card.applies_when.risk_patterns == ["scope drift", "unbounded edit"]


def test_empty_draft_risk_patterns_fall_back_to_blockers(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    review = make_review(blockers=["b1", "b2"])
    result = create_card_from_draft(
        make_task(), review, ("reported_passed", "unverified"),
        {"memory": VALID_MEMORY, "why": VALID_WHY, "risk_patterns": []},
        store, default_config(), "2026-01-01T00:00:00Z",
    )
    assert result["card"].applies_when.risk_patterns == ["b1", "b2"]


# --------------------------------------------------------------------------- transferability


def test_transferable_when_files_are_generic(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    # No path separators and no source extensions -> not repo-specific.
    review = make_review(changed_files=["README", "Makefile", "notes"])
    result = create_card_from_draft(
        make_task(), review, ("reported_passed", "unverified"),
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    assert result["card"].transferability == "transferable"


def test_local_only_when_all_files_repo_specific(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    review = make_review(changed_files=["src/a.py", "src/b.py"])
    result = create_card_from_draft(
        make_task(), review, ("reported_passed", "unverified"),
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    assert result["card"].transferability == "local_only"


def test_mixed_files_not_repo_specific_is_transferable(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    # One generic file poisons the set -> not all repo-specific -> transferable.
    review = make_review(changed_files=["src/a.py", "notes"])
    result = create_card_from_draft(
        make_task(), review, ("reported_passed", "unverified"),
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    assert result["card"].transferability == "transferable"


def test_file_with_extension_but_no_slash_is_repo_specific(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    review = make_review(changed_files=["service.py"])
    result = create_card_from_draft(
        make_task(), review, ("reported_passed", "unverified"),
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    assert result["card"].transferability == "local_only"


# --------------------------------------------------------------------------- determinism


def test_classify_task_types_determinism() -> None:
    assert classify_task_types("Fix the bug in forge/service.py") == ["bugfix"]
    assert classify_task_types("Add a test for the config loader") == ["config", "testing"]
    assert classify_task_types("Refactor the plugin tooling and review docs") == (
        ["docs", "plugin", "refactor", "review", "tooling"]
    )
    assert classify_task_types("Update the telemetry build and package config") == (
        ["build", "config", "telemetry"]
    )
    assert classify_task_types("") == ["general"]
    assert classify_task_types("do something unrelated") == ["general"]
    # Deterministic: same input -> same output, sorted.
    assert classify_task_types("test docs memory review") == classify_task_types(
        "review memory docs test")


def test_derive_modules_determinism() -> None:
    assert derive_modules(["forge/mcp_server.py", "forge/config.py"]) == ["forge"]
    assert derive_modules(["a/b/c.py", "a/d.py", "x/y.py"]) == ["a", "x"]
    assert derive_modules(["file.py"]) == []  # no directory -> skipped
    assert derive_modules(["top/file.py", "loose.py"]) == ["top"]
    assert derive_modules([]) == []
    assert derive_modules(None) == []  # type: ignore[arg-type]
    # Sorted unique.
    assert derive_modules(["z/a.py", "m/b.py", "z/c.py"]) == ["m", "z"]


def test_is_repo_specific_edge_cases() -> None:
    assert is_repo_specific([]) is False  # empty -> transferable
    assert is_repo_specific(["forge/service.py"]) is True
    assert is_repo_specific(["service.py"]) is True  # extension counts
    assert is_repo_specific(["README"]) is False  # no slash, no ext
    assert is_repo_specific(["a/b.py", "c/d.py"]) is True
    assert is_repo_specific(["a/b.py", "README"]) is False  # mixed


# --------------------------------------------------------------------------- confidence table


def test_derive_confidence_unverified_passed_is_medium() -> None:
    assert derive_confidence("unverified", {"passed": True, "blockers": []}) == "medium"


def test_derive_confidence_unverified_no_review_is_low() -> None:
    assert derive_confidence("unverified", None) == "low"


def test_derive_confidence_unverified_review_not_passed_is_low() -> None:
    assert derive_confidence("unverified", {"passed": False, "blockers": []}) == "low"


def test_derive_confidence_mismatch_returns_none() -> None:
    assert derive_confidence("mismatch", {"passed": True}) is None
    assert derive_confidence("mismatch", None) is None


def test_derive_confidence_honest_failure_with_blockers_is_medium() -> None:
    assert derive_confidence("honest_failure", {"passed": False, "blockers": ["x"]}) == "medium"


def test_derive_confidence_honest_failure_without_blockers_is_low() -> None:
    assert derive_confidence("honest_failure", {"passed": False, "blockers": []}) == "low"
    assert derive_confidence("honest_failure", None) == "low"


def test_derive_confidence_verified_passed_is_high() -> None:
    # documented-future: verified is unreachable from derive_honesty today,
    # but the table maps verified + passed -> high.
    assert derive_confidence("verified", {"passed": True}) == "high"


# --------------------------------------------------------------------------- end-to-end via derive_honesty


def test_full_flow_unverified_passed_yields_medium_card(tmp_path: Path) -> None:
    """Honesty derived from derive_honesty, then factory, matches the table."""
    from forge.telemetry.honesty import derive_honesty

    store = make_store(tmp_path)
    honesty = derive_honesty(True, [{"status": "passed"}])
    assert honesty == ("reported_passed", "unverified")
    result = create_card_from_draft(
        make_task(), make_review(passed=True), honesty,
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    assert result["card"].confidence == "medium"
    assert result["card"].entry_type == "validation_memory"


def test_full_flow_mismatch_yields_no_card(tmp_path: Path) -> None:
    from forge.telemetry.honesty import derive_honesty

    store = make_store(tmp_path)
    honesty = derive_honesty(True, [{"status": "failed"}])
    assert honesty == ("reported_failed", "mismatch")
    result = create_card_from_draft(
        make_task(), make_review(passed=False), honesty,
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    assert "card" not in result
    assert "contradicts evidence" in result["warning"]
    assert store.read_active() == []


def test_full_flow_honest_failure_yields_pitfall(tmp_path: Path) -> None:
    from forge.telemetry.honesty import derive_honesty

    store = make_store(tmp_path)
    honesty = derive_honesty(False, [{"status": "passed"}])
    assert honesty == ("reported_passed", "honest_failure")
    review = make_review(passed=False, blockers=["syntax error in forge/service.py"])
    result = create_card_from_draft(
        make_task(), review, honesty,
        {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
        "2026-01-01T00:00:00Z",
    )
    assert result["card"].entry_type == "pitfall_memory"
    assert result["card"].confidence == "medium"


# --------------------------------------------------------------------------- id sequence


def test_card_ids_are_sequential_across_creations(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    for n in range(3):
        result = create_card_from_draft(
            make_task(task_id=f"task_{n}"), make_review(),
            ("reported_passed", "unverified"),
            {"memory": VALID_MEMORY, "why": VALID_WHY}, store, default_config(),
            "2026-01-01T00:00:00Z",
        )
        assert result["card"].card_id == f"mem_{n + 1:06d}"
    assert [c.card_id for c in store.read_active()] == [
        "mem_000001", "mem_000002", "mem_000003"]
