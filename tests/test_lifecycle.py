from pathlib import Path

from forge.service import ForgeService


def start(service: ForgeService, repo: Path, expected: list[str] | None = None):
    return service.forge_start_task("implement feature", str(repo), expected_files=expected)


def test_start_review_finish_happy_path(service, repo):
    result = start(service, repo, ["feature.py"])
    assert result["state"] == "active"
    assert result["prepared_context"]["task_text"] == "implement feature"
    (repo / "feature.py").write_text("value = 1\n", encoding="utf-8")
    reviewed = service.forge_review_changes(result["task_id"], [{"status": "passed"}])
    assert reviewed["state"] == "reviewed"
    assert reviewed["review"]["evidence_status"] == "reported_passed"
    finished = service.forge_finish_task(result["task_id"], True, "done")
    assert finished["state"] == "completed" and finished["verified"] is True


def test_success_before_review_rejected_but_failure_allowed(service, repo):
    task_id = start(service, repo)["task_id"]
    assert not service.forge_finish_task(task_id, True, "premature")["ok"]
    failed = service.forge_finish_task(task_id, False, "could not complete")
    assert failed["state"] == "failed" and failed["lifecycle_complete"] is True


def test_stale_review_rejected(service, repo):
    task_id = start(service, repo, ["a.py"])["task_id"]
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert service.forge_review_changes(task_id)["ok"]
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    result = service.forge_finish_task(task_id, True, "done")
    assert not result["ok"] and "stale" in result["error"]


def test_terminal_finish_is_idempotent_without_duplicate_event(service, repo):
    task_id = start(service, repo)["task_id"]
    first = service.forge_finish_task(task_id, False, "failed")
    count = len((service.runtime_root / "telemetry.jsonl").read_text().splitlines())
    assert service.forge_finish_task(task_id, False, "different") == first
    assert len((service.runtime_root / "telemetry.jsonl").read_text().splitlines()) == count


def test_degraded_is_unverified_and_cannot_upgrade(service, repo):
    task_id = start(service, repo)["task_id"]
    result = service.forge_submit_outcome(True, "reported", "backend outage", task_id=task_id)
    assert result["state"] == "degraded"
    assert result["verified"] is False and result["lifecycle_complete"] is False
    assert service.forge_finish_task(task_id, True, "done")["state"] == "degraded"

