from pathlib import Path

from forge.review.baseline import capture_tree
from forge.service import ForgeService


def start(service: ForgeService, repo: Path, expected: list[str] | None = None):
    return service.start_task("implement feature", str(repo), expected_files=expected)


def test_start_review_finish_happy_path(service, repo):
    result = start(service, repo, ["feature.py"])
    assert result["state"] == "active"
    assert result["prepared_context"]["task_text"] == "implement feature"
    guidance = result["prepared_context"]["lifecycle_guidance"]
    assert "classification" in guidance["declare_before_work"]
    assert "independent_review_loop" in guidance["declare_before_work"]
    assert "CONTROLLED_IMPLEMENTATION" in guidance["independent_review_loop_rule"]
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    reviewed = service.review_changes(result["task_id"], [{"status": "passed"}])
    assert reviewed["state"] == "reviewed"
    assert reviewed["review"]["evidence_status"] == "reported_passed"
    finish_guidance = reviewed["finish_guidance"]
    assert "memory_draft" in " ".join(finish_guidance["before_finish_task"])
    assert "memory_feedback" in " ".join(finish_guidance["before_finish_task"])
    finished = service.finish_task(result["task_id"], True, "done")
    assert finished["state"] == "completed" and finished["verified"] is True


def test_review_finish_guidance_lists_injected_memory_cards(service, repo):
    task_id = start(service, repo, ["feature.py"])["task_id"]
    task = service.tasks.get(task_id)
    task.injected_memory_cards = ["mem_1", "mem_2"]
    service.tasks.append(task)
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    reviewed = service.review_changes(task_id, [{"status": "passed"}])
    assert reviewed["finish_guidance"]["memory_feedback_required_for"] == ["mem_1", "mem_2"]


def test_non_mutation_finish_succeeds_without_review(service, repo):
    task_id = start(service, repo)["task_id"]
    result = service.finish_task(task_id, True, "read-only review, no changes")
    assert result["ok"] is True
    assert result["state"] == "completed"
    assert result["verified"] is True


def test_mutation_finish_without_review_rejected(service, repo):
    task_id = start(service, repo, ["x.py"])["task_id"]
    (repo / "x.py").write_text("x=1\n", encoding="utf-8")
    result = service.finish_task(task_id, True, "done")
    assert not result["ok"]
    assert "requires a passing review" in result["error"]


def test_failure_finish_allowed_without_review(service, repo):
    task_id = start(service, repo)["task_id"]
    failed = service.finish_task(task_id, False, "could not complete")
    assert failed["state"] == "failed" and failed["lifecycle_complete"] is True


def test_non_mutation_bypass_with_dirty_worktree(service, repo):
    # A pre-existing dirty file is NOT a task-owned change; a read-only task in
    # a dirty repo still finishes successfully without review.
    (repo / "dirty.txt").write_text("pre-existing\n", encoding="utf-8")
    task_id = start(service, repo)["task_id"]
    result = service.finish_task(task_id, True, "read-only, no task changes")
    assert result["ok"] is True
    assert result["state"] == "completed"


def test_stale_review_rejected(service, repo):
    task_id = start(service, repo, ["a.py"])["task_id"]
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert service.review_changes(task_id)["ok"]
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    result = service.finish_task(task_id, True, "done")
    assert not result["ok"] and "stale" in result["error"]


def test_terminal_finish_is_idempotent_without_duplicate_event(service, repo):
    task_id = start(service, repo)["task_id"]
    first = service.finish_task(task_id, False, "failed")
    count = len((service.runtime_root / "telemetry.jsonl").read_text().splitlines())
    assert service.finish_task(task_id, False, "different") == first
    assert len((service.runtime_root / "telemetry.jsonl").read_text().splitlines()) == count


def test_degraded_is_unverified_and_cannot_upgrade(service, repo):
    task_id = start(service, repo)["task_id"]
    result = service.submit_outcome(True, "reported", "backend outage", task_id=task_id)
    assert result["state"] == "degraded"
    assert result["verified"] is False and result["lifecycle_complete"] is False
    assert service.finish_task(task_id, True, "done")["state"] == "degraded"


# --------------------------------------------------- baseline-aware lifecycle


def test_baseline_status_in_prepared_context(service, repo):
    result = start(service, repo)
    assert result["prepared_context"]["baseline_status"] == "captured"


def test_dirty_repo_before_start_separated(service, repo):
    (repo / "dirty.txt").write_text("pre-existing\n")
    task_id = start(service, repo)["task_id"]
    (repo / "agent.txt").write_text("agent change\n")
    reviewed = service.review_changes(task_id)
    task_changed = reviewed["review"]["task_changed_files"]
    preexisting = reviewed["review"]["preexisting_dirty_files"]
    assert "agent.txt" in task_changed
    assert "dirty.txt" in preexisting
    assert "dirty.txt" not in task_changed


def test_post_review_edit_to_nontask_file_stale(service, repo):
    (repo / "dirty.txt").write_text("old\n")
    task_id = start(service, repo, ["a.py"])["task_id"]
    (repo / "a.py").write_text("x=1\n")
    assert service.review_changes(task_id)["ok"]
    # Edit a pre-existing dirty file AFTER review ─ still makes review stale.
    (repo / "dirty.txt").write_text("new\n")
    result = service.finish_task(task_id, True, "done")
    assert not result["ok"] and "stale" in result["error"]


def test_no_mutation_finish_failure_no_review(service, repo):
    task_id = start(service, repo)["task_id"]
    result = service.finish_task(task_id, False, "gave up")
    assert result["state"] == "failed" and result["lifecycle_complete"] is True


def test_mutation_success_finish_requires_fresh_review(service, repo):
    task_id = start(service, repo)["task_id"]
    (repo / "x.py").write_text("x=1\n")
    assert service.review_changes(task_id)["ok"]
    (repo / "x.py").write_text("x=2\n")
    result = service.finish_task(task_id, True, "done")
    assert not result["ok"] and "stale" in result["error"]


def test_concurrent_different_sessions_blocked(tmp_path, repo):
    """Two tasks on the same repo with explicit different host_session_ids
    should be blocked — one agent per repo at a time."""
    from forge.service import ForgeService
    ids = iter(["task_a", "task_b"])
    svc = ForgeService(tmp_path / "runtime", clock=lambda: 0,
                       id_factory=lambda seed: next(ids))
    result_a = svc.start_task("task a", str(repo), host_session_id="sess_a")
    assert result_a["ok"]
    result_b = svc.start_task("task b", str(repo), host_session_id="sess_b")
    assert not result_b["ok"]
    assert "another active task" in result_b["error"]


def test_concurrent_same_session_idempotent(tmp_path, repo):
    """Same host_session_id → idempotent, not blocked."""
    from forge.service import ForgeService
    ids = iter(["t1", "t2"])
    svc = ForgeService(tmp_path / "runtime", clock=lambda: 0,
                       id_factory=lambda seed: next(ids))
    first = svc.start_task("task", str(repo), host_session_id="sess")
    assert first["ok"]
    second = svc.start_task("other", str(repo), host_session_id="sess")
    assert second["ok"]
    assert second["idempotent"]
    assert second["task_id"] == first["task_id"]


def test_concurrent_no_session_only_warns(tmp_path, repo):
    """No host_session_id on either task → cannot determine ownership → warn, not block."""
    from forge.service import ForgeService
    ids = iter(["task_a", "task_b"])
    svc = ForgeService(tmp_path / "runtime", clock=lambda: 0,
                       id_factory=lambda seed: next(ids))
    result_a = svc.start_task("task a", str(repo))
    assert result_a["ok"]
    result_b = svc.start_task("task b", str(repo))
    assert result_b["ok"]
    warnings = " ".join(result_b.get("warnings", []))
    assert "another active task" in warnings.lower()


# --------------------------------------------------- transcript evidence lifecycle


def test_edit_revert_no_deadlock(service, repo):
    task_id = start(service, repo)["task_id"]
    (repo / "base.txt").write_text("edited\n", encoding="utf-8")
    from subprocess import run as sub_run
    sub_run(["git", "-C", str(repo), "checkout", "--", "base.txt"],
            check=True, capture_output=True)
    result = service.finish_task(task_id, True, "reverted edit")
    assert result["ok"] is True
    assert result["state"] == "completed"


def test_transcript_has_changes_with_baseline(service, repo):
    task_id = start(service, repo, ["a.py"])["task_id"]
    task = service.tasks.get(task_id)
    task.session_digest = {"edited_files": ["a.py"], "edited_files_digest": "x"}
    (repo / "a.py").write_text("x=1\n", encoding="utf-8")
    reviewed = service.review_changes(task_id)
    assert reviewed["ok"]
    result = service.finish_task(task_id, True, "done")
    assert result["ok"]
    assert result["state"] == "completed"


def test_transcript_bypass_despite_concurrent_worktree_edit(service, repo):
    """Per-session digest match allows finish despite concurrent worktree edits."""
    task_id = start(service, repo, ["a.py"])["task_id"]
    task = service.tasks.get(task_id)
    task.session_digest = {"edited_files": ["a.py"], "edited_files_digest": "x"}
    (repo / "a.py").write_text("x=1\n", encoding="utf-8")
    reviewed = service.review_changes(task_id)
    assert reviewed["ok"]
    (repo / "b.py").write_text("y=2\n", encoding="utf-8")
    result = service.finish_task(task_id, True, "done")
    assert result["ok"]
    assert result["state"] == "completed"


def test_transcript_bypass_with_clean_worktree(service, repo):
    task_id = start(service, repo)["task_id"]
    task = service.tasks.get(task_id)
    task.session_digest = {"edited_files": [], "edited_files_digest": "y"}
    result = service.finish_task(task_id, True, "no changes per both sources")
    assert result["ok"] is True
    assert result["state"] == "completed"


def test_session_digest_survives_append_round_trip(service, repo):
    task_id = start(service, repo)["task_id"]
    task = service.tasks.get(task_id)
    task.session_digest = {
        "edited_files": ["a.py"],
        "edited_files_digest": "abc",
        "test_runs": [{"command": "pytest", "output": "3 passed"}],
    }
    service.tasks.append(task)
    reloaded = service.tasks.get(task_id)
    assert reloaded is not None
    assert reloaded.session_digest is not None
    assert reloaded.session_digest["edited_files"] == ["a.py"]
    assert reloaded.session_digest["test_runs"] == [{"command": "pytest", "output": "3 passed"}]
