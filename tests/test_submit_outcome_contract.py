"""Contract tests for submit_outcome: a real, resolvable task_id is required."""


def test_submit_outcome_without_task_id_is_rejected(service, repo):
    before = len(service.tasks.all())
    result = service.submit_outcome(True, "reported", "backend outage")
    assert result["ok"] is False
    assert result["task_id"] is None
    assert result["required_next_action"]
    assert "task_id" in result["error"]
    assert len(service.tasks.all()) == before


def test_submit_outcome_with_bogus_task_id_is_rejected(service, repo):
    before = len(service.tasks.all())
    result = service.submit_outcome(True, "reported", "backend outage", task_id="task_bogus")
    assert result["ok"] is False
    assert result["task_id"] == "task_bogus"
    assert result["error"] == "task does not exist"
    assert result["required_next_action"] == "start a task first"
    assert len(service.tasks.all()) == before


def test_submit_outcome_with_real_task_id_degrades(service, repo):
    started = service.start_task("implement feature", str(repo))
    task_id = started["task_id"]
    result = service.submit_outcome(True, "reported", "backend outage", task_id=task_id)
    assert result["ok"] is True
    assert result["state"] == "degraded"
    assert result["verified"] is False
    assert result["lifecycle_complete"] is False


def test_submit_outcome_degraded_is_idempotent(service, repo):
    started = service.start_task("implement feature", str(repo))
    task_id = started["task_id"]
    first = service.submit_outcome(True, "reported", "backend outage", task_id=task_id)
    second = service.submit_outcome(True, "different", "other reason", task_id=task_id)
    assert second == first
