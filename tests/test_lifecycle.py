from pathlib import Path

from forge.review.baseline import capture_tree
from forge.service import ForgeService


def start(service: ForgeService, repo: Path, expected: list[str] | None = None):
    return service.start_task("implement feature", str(repo), expected_files=expected)


def test_start_review_finish_happy_path(service, repo):
    result = start(service, repo, ["feature.py"])
    assert result["state"] == "active"
    assert result["prepared_context"]["task_text"] == "implement feature"
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    reviewed = service.review_changes(result["task_id"], [{"status": "passed"}])
    assert reviewed["state"] == "reviewed"
    assert reviewed["review"]["evidence_status"] == "reported_passed"
    finished = service.finish_task(result["task_id"], True, "done")
    assert finished["state"] == "completed" and finished["verified"] is True


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


def test_concurrent_task_warning(tmp_path, repo):
    from forge.service import ForgeService
    ids = iter(["task_a", "task_b"])
    svc = ForgeService(tmp_path / "runtime", clock=lambda: 0,
                       id_factory=lambda seed: next(ids))
    result_a = svc.start_task("task a", str(repo), host_session_id="sess_a")
    result_b = svc.start_task("task b", str(repo), host_session_id="sess_b")
    warnings = " ".join(result_b.get("warnings", []))
    assert "another active task" in warnings.lower()

