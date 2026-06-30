from __future__ import annotations

import asyncio
import json
from pathlib import Path

from forge.mcp_server import PUBLIC_TOOLS, mcp
from forge.memory.cards import AppliesWhen, MemoryCard
from forge.memory.feedback_store import FeedbackStore
from forge.memory.store import MemoryStore
from forge.service import ForgeService


# ----------------------------------------------------------- helpers


def _seed_card(store: MemoryStore, card_id: str, repo_root: str,
               memory: str = "always anchor memory cards in concrete file paths like forge/service.py",
               why: str = "previous regression: cards without anchors were generic and ignored") -> MemoryCard:
    card = MemoryCard(
        card_id=card_id,
        memory=memory,
        why=why,
        avoid="",
        use_as="",
        entry_type="validation_memory",
        transferability="local_only",
        source_repo_root=repo_root,
        source_repo_id=repo_root,
        applies_when=AppliesWhen(
            task_types=["tooling"], files=["forge/service.py"],
            modules=["forge"], risk_patterns=["scope drift"],
        ),
        confidence="medium",
        source_task_ids=[],
        supersedes=[],
        superseded_by=None,
        created_at="2026-01-01T00:00:00Z",
    )
    store.add_card(card)
    return card


def _start_review_finish(service: ForgeService, repo: Path, task_id: str,
                         success: bool = True, *, memory_draft: dict | None = None,
                         memory_feedback: list[dict] | None = None,
                         commands_run: list[str] | None = None) -> dict:
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    task = service.tasks.get(task_id)
    assert task is not None
    task.session_digest = {
        "edited_files": ["feature.py"],
        "edited_files_digest": "feature-edit-1",
        "test_runs": [],
    }
    service.tasks.append(task)
    service.review_changes(task_id, [{"status": "passed"}])
    return service.finish_task(
        task_id, success, "done" if success else "failed",
        commands_run=commands_run, memory_draft=memory_draft,
        memory_feedback=memory_feedback)


# ----------------------------------------------------------- tests


def test_finish_with_draft_creates_card(service: ForgeService, repo: Path) -> None:
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    draft = {
        "memory": "When wiring telemetry events, pass the narrative fields through to the verdict.",
        "why": "Prior integration dropped agent_step_intent silently in the review_completed event.",
    }
    result = _start_review_finish(service, repo, task_id, success=True, memory_draft=draft)
    assert result["ok"] is True
    cards_file = service.runtime_root / "memory" / "memory_cards.json"
    assert cards_file.exists()
    cards = service.memory.read_active()
    assert len(cards) == 1
    card = cards[0]
    assert card.memory == draft["memory"]
    assert card.card_id.startswith("mem_")
    # Backend-filled fields.
    assert card.entry_type == "validation_memory"
    assert card.source_repo_root == str(repo)
    assert card.source_repo_id == str(repo)
    assert card.source_task_ids == [task_id]
    assert card.supersedes == []
    assert card.confidence in {"high", "medium", "low"}


def test_finish_with_feedback_persisted(service: ForgeService, repo: Path) -> None:
    store = service.memory
    repo_root = str(repo)
    seeded = _seed_card(store, "mem_000001", repo_root)
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    # The seeded card must be in the injected set on the persisted task.
    task = service.tasks.get(task_id)
    assert task is not None
    assert seeded.card_id in task.injected_memory_cards
    feedback_path = service.runtime_root / "memory" / "memory_feedback.jsonl"
    feedback_store = FeedbackStore(feedback_path, clock=service.clock)
    # Valid feedback for an injected card.
    valid_feedback = [
        {"card_id": seeded.card_id, "rating": "helpful",
         "reason": "matched the exact integration boundary"},
    ]
    # Feedback for a card_id that was NOT injected must be rejected/skipped.
    bogus_feedback = [
        {"card_id": "mem_999999", "rating": "helpful", "reason": "never injected"},
    ]
    result = _start_review_finish(
        service, repo, task_id, success=True,
        memory_feedback=valid_feedback + bogus_feedback)
    assert result["ok"] is True
    records = feedback_store.read_feedback()
    assert len(records) == 1
    assert records[0]["card_id"] == seeded.card_id
    assert records[0]["rating"] == "helpful"
    assert records[0]["task_id"] == task_id
    # The bogus card_id was never persisted.
    assert all(r["card_id"] != "mem_999999" for r in records)


def test_review_event_carries_narrative_fields(service: ForgeService, repo: Path) -> None:
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    task = service.tasks.get(task_id)
    assert task is not None
    task.session_digest = {
        "edited_files": ["feature.py"],
        "edited_files_digest": "feature-edit-1",
        "test_runs": [],
    }
    service.tasks.append(task)
    service.review_changes(
        task_id, [{"status": "passed"}],
        agent_step_intent="wire narrative fields through service.py",
        target_behavior_claim="review_completed event carries agent_step_intent",
        owner_boundary_claim="edits only forge/service.py and forge/mcp_server.py",
        proof_plan="parse telemetry.jsonl and assert the field is present")
    telemetry_path = service.runtime_root / "telemetry.jsonl"
    events = [json.loads(line) for line in telemetry_path.read_text().splitlines() if line.strip()]
    review_events = [e for e in events if e.get("event") == "review_completed"]
    assert len(review_events) == 1
    ev = review_events[0]
    assert ev["agent_step_intent"] == "wire narrative fields through service.py"
    assert ev["target_behavior_claim"] == "review_completed event carries agent_step_intent"
    assert ev["owner_boundary_claim"] == "edits only forge/service.py and forge/mcp_server.py"
    assert ev["proof_plan"] == "parse telemetry.jsonl and assert the field is present"
    assert "claim_evidence_status" in ev


def test_mcp_public_surface_stays_five_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    assert {t.name for t in tools} == set(PUBLIC_TOOLS)
    assert len(PUBLIC_TOOLS) == 5


def test_archived_card_not_in_start_brief(service: ForgeService, repo: Path) -> None:
    store = service.memory
    repo_root = str(repo)
    active = _seed_card(store, "mem_000010", repo_root)
    archived = _seed_card(store, "mem_000011", repo_root,
                          memory="archived card about forge/config.py defaults loading",
                          why="superseded by a higher-quality card after maintenance review")
    store.archive_card(archived.card_id, "low quality")
    # Active set must contain only the un-archived card.
    active_ids = {c.card_id for c in store.read_active()}
    assert active.card_id in active_ids
    assert archived.card_id not in active_ids
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    prepared = start["prepared_context"]
    # The archived card must not appear anywhere in the injected brief.
    assert archived.card_id not in prepared["memory_brief"]
    # And it must not be in the injected_memory_cards on the task.
    task = service.tasks.get(start["task_id"])
    assert task is not None
    assert archived.card_id not in task.injected_memory_cards
    assert active.card_id in task.injected_memory_cards or \
        active.card_id in prepared["memory_brief"]


def test_finish_without_draft_does_not_create_memory_cards(service: ForgeService, repo: Path) -> None:
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    _start_review_finish(service, repo, start["task_id"], success=True)
    cards_file = service.runtime_root / "memory" / "memory_cards.json"
    assert not cards_file.exists()


def test_finish_event_carries_honesty_and_commands(service: ForgeService, repo: Path) -> None:
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    _start_review_finish(service, repo, task_id, success=True,
                         commands_run=["pytest -q", "ruff check"])
    telemetry_path = service.runtime_root / "telemetry.jsonl"
    events = [json.loads(line) for line in telemetry_path.read_text().splitlines() if line.strip()]
    finished = [e for e in events if e.get("event") == "task_finished"]
    assert len(finished) == 1
    ev = finished[0]
    assert ev["success"] is True
    assert ev["commands_run"] == ["pytest -q", "ruff check"]
    assert "finish_claim_honesty" in ev
    assert "claim_evidence_status" in ev


def test_missing_feedback_when_cards_injected_warns(service: ForgeService, repo: Path) -> None:
    store = service.memory
    repo_root = str(repo)
    _seed_card(store, "mem_000020", repo_root)
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    task = service.tasks.get(task_id)
    assert task is not None and task.injected_memory_cards  # a card was injected
    result = _start_review_finish(service, repo, task_id, success=True, memory_feedback=None)
    assert result["ok"] is True
    assert any("memory feedback missing" in w for w in result["warnings"])
    finished = next(
        event for event in service.telemetry.read_all()
        if event.get("event") == "task_finished"
    )
    assert finished["memory_feedback_status"] == "missing"
    assert finished["injected_memory_cards"] == task.injected_memory_cards


# ----------------------------------------------------------- finish response fields (Issue 2)

def test_finish_success_exposes_lifecycle_verified_and_verification_basis(service: ForgeService, repo: Path) -> None:
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    result = _start_review_finish(service, repo, task_id, success=True)
    assert result["ok"] is True
    assert result["lifecycle_verified"] is True
    assert result["verification_basis"] == "fresh_review_of_session_captured_mutations"
    assert result["mutation_capture_status"] == "no_mutation_risk"
    assert result["validation_status"] == "not_run"
    assert result["claim_honesty"] == "unverified"
    assert result["verified"] is True  # deprecated alias still present


def test_finish_success_with_observed_passed_validation(service: ForgeService, repo: Path) -> None:
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    task = service.tasks.get(task_id)
    assert task is not None
    task.session_digest = {
        "edited_files": ["feature.py"],
        "edited_files_digest": "feature-edit-1",
        "test_runs": [{"command": "pytest", "output": "3 passed", "exit_code": 0}],
        "mutation_status": "captured_mutation",
    }
    service.tasks.append(task)
    service.review_changes(task_id, [{"status": "passed"}])
    result = service.finish_task(task_id, True, "done")
    assert result["ok"] is True
    assert result["validation_status"] == "observed_passed"
    assert result["claim_honesty"] == "verified"
    assert result["verification_basis"] == "fresh_review_of_session_captured_mutations"
    assert result["mutation_capture_status"] == "captured_mutation"


def test_finish_success_observed_failed_with_remaining_issues(service: ForgeService, repo: Path) -> None:
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    task = service.tasks.get(task_id)
    assert task is not None
    task.session_digest = {
        "edited_files": ["feature.py"],
        "edited_files_digest": "feature-edit-1",
        "test_runs": [{"command": "pytest", "output": "2 failed", "exit_code": 1}],
        "mutation_status": "captured_mutation",
    }
    service.tasks.append(task)
    service.review_changes(task_id, [{"status": "passed"}])
    result = service.finish_task(
        task_id, True, "done",
        remaining_issues=["tests show 2 failures, see above"],
        validation_evidence=[{"status": "failed"}])
    assert result["ok"] is True
    assert result["validation_status"] == "observed_failed"
    assert result["claim_honesty"] == "mismatch"
    assert "tests show 2 failures" in result["remaining_issues"][0]


def test_finish_failure_exposes_verification_basis(service: ForgeService, repo: Path) -> None:
    start = service.start_task("implement feature", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    task = service.tasks.get(task_id)
    assert task is not None
    task.session_digest = {
        "edited_files": ["feature.py"],
        "edited_files_digest": "feature-edit-1",
        "test_runs": [],
        "mutation_status": "captured_mutation",
    }
    service.tasks.append(task)
    service.review_changes(task_id, [{"status": "failed"}])
    result = service.finish_task(task_id, False, "failed due to tests")
    assert result["ok"] is True
    assert result["lifecycle_verified"] is False
    assert result["verification_basis"] == "explicit_failure"
    assert result["claim_honesty"] == "honest_failure"


def test_submit_outcome_exposes_degraded_fields(service: ForgeService, repo: Path) -> None:
    start = service.start_task("test task", str(repo), expected_files=["feature.py"])
    task_id = start["task_id"]
    result = service.submit_outcome(False, "backend down", "infra outage", task_id=task_id)
    assert result["verified"] is False
    assert result["lifecycle_verified"] is False
    assert result["verification_basis"] == "degraded_unverified"
    assert result["mutation_capture_status"] == "not_applicable"
    assert result["validation_status"] == "not_run"
    assert result["claim_honesty"] == "degraded"
