import json

from forge.telemetry.events import event, review_completed_event, task_finished_event
from forge.telemetry.honesty import derive_honesty
from forge.telemetry.writer import TelemetryWriter


def test_versioned_bounded_and_nonblocking(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = TelemetryWriter(path, max_bytes=20)
    assert writer.append({"schema_version": 1}) is None
    assert json.loads(path.read_text().splitlines()[0])["schema_version"] == 1
    assert writer.append({"schema_version": 1}) is not None
    bad = TelemetryWriter(tmp_path / "directory")
    bad.path.mkdir()
    assert "failed" in bad.append({"schema_version": 1})


def test_generic_event_keeps_schema_version_and_fields():
    result = event("ping", "task-1", "2026-06-21T00:00:00Z", extra=42)
    assert result == {"schema_version": 1, "event": "ping", "task_id": "task-1",
                      "timestamp": "2026-06-21T00:00:00Z", "extra": 42}


def test_review_completed_event_carries_four_narrative_fields_and_evidence_status():
    result = review_completed_event(
        "task-1", "2026-06-21T00:00:00Z",
        passed=True, evidence_status="reported_passed",
        agent_step_intent="add telemetry honesty layer",
        target_behavior_claim="events carry narrative fields",
        owner_boundary_claim="telemetry module only",
        proof_plan="run pytest -q",
    )
    assert result["schema_version"] == 1
    assert result["event"] == "review_completed"
    assert result["task_id"] == "task-1"
    assert result["timestamp"] == "2026-06-21T00:00:00Z"
    assert result["passed"] is True
    assert result["claim_evidence_status"] == "reported_passed"
    assert result["agent_step_intent"] == "add telemetry honesty layer"
    assert result["target_behavior_claim"] == "events carry narrative fields"
    assert result["owner_boundary_claim"] == "telemetry module only"
    assert result["proof_plan"] == "run pytest -q"


def test_review_completed_event_omits_none_narrative_fields():
    result = review_completed_event("t", "ts", passed=False, evidence_status="not_run")
    assert result["event"] == "review_completed"
    assert result["passed"] is False
    assert result["claim_evidence_status"] == "not_run"
    for absent in ("agent_step_intent", "target_behavior_claim",
                   "owner_boundary_claim", "proof_plan"):
        assert absent not in result


def test_review_completed_event_passes_through_extra_fields():
    result = review_completed_event("t", "ts", passed=True, evidence_status="unknown",
                                    diff_digest="abc", changed_files=["a.py"])
    assert result["diff_digest"] == "abc"
    assert result["changed_files"] == ["a.py"]


def test_task_finished_event_carries_commands_run_and_honesty_fields():
    result = task_finished_event(
        "task-1", "2026-06-21T00:00:00Z",
        success=True, commands_run=["uv run python -m pytest -q"],
        finish_claim_honesty="unverified", claim_evidence_status="reported_passed",
    )
    assert result["schema_version"] == 1
    assert result["event"] == "task_finished"
    assert result["task_id"] == "task-1"
    assert result["timestamp"] == "2026-06-21T00:00:00Z"
    assert result["success"] is True
    assert result["commands_run"] == ["uv run python -m pytest -q"]
    assert result["finish_claim_honesty"] == "unverified"
    assert result["claim_evidence_status"] == "reported_passed"


def test_task_finished_event_omits_none_optional_fields():
    result = task_finished_event("t", "ts", success=False)
    assert result["event"] == "task_finished"
    assert result["success"] is False
    for absent in ("commands_run", "finish_claim_honesty", "claim_evidence_status"):
        assert absent not in result


def test_derive_honesty_success_reported_passed_is_unverified():
    assert derive_honesty(True, [{"status": "passed"}]) == ("reported_passed", "unverified")


def test_derive_honesty_success_not_run_is_unverified():
    assert derive_honesty(True, None) == ("not_run", "unverified")


def test_derive_honesty_success_unknown_is_unverified():
    assert derive_honesty(True, [{"status": "inconclusive"}]) == ("unknown", "unverified")


def test_derive_honesty_failure_is_honest_failure_regardless_of_evidence():
    assert derive_honesty(False, [{"status": "passed"}]) == ("reported_passed", "honest_failure")
    assert derive_honesty(False, None) == ("not_run", "honest_failure")


def test_derive_honesty_success_reported_failed_is_mismatch():
    assert derive_honesty(True, [{"status": "failed"}]) == ("reported_failed", "mismatch")


def test_derive_honesty_never_emits_verified_without_session_digest():
    # verified requires an independently-observed pass via session_digest.
    # Without session_digest, classify_evidence cannot produce observed_passed,
    # so verified is unreachable in that path.
    for success in (True, False):
        for evidence in (None, [{"status": "passed"}], [{"status": "failed"}],
                         [{"status": "weird"}]):
            _, honesty = derive_honesty(success, evidence, session_digest=None)
            assert honesty != "verified"


def test_derive_honesty_observed_passed_is_verified():
    digest = {"test_runs": [{"command": "pytest", "output": "3 passed"}]}
    claim, honesty = derive_honesty(True, None, session_digest=digest)
    assert claim == "observed_passed"
    assert honesty == "verified"


def test_derive_honesty_observed_failed_success_false_is_honest_failure():
    digest = {"test_runs": [{"command": "pytest", "output": "2 failed"}]}
    claim, honesty = derive_honesty(False, None, session_digest=digest)
    assert claim == "observed_failed"
    assert honesty == "honest_failure"


def test_derive_honesty_observed_failed_success_true_is_mismatch():
    digest = {"test_runs": [{"command": "pytest", "output": "2 failed"}]}
    claim, honesty = derive_honesty(True, None, session_digest=digest)
    assert claim == "observed_failed"
    assert honesty == "mismatch"


def test_derive_honesty_exit_code_mismatch_is_mismatch():
    digest = {"test_runs": [{"command": "pytest", "output": "3 passed", "exit_code": 1}]}
    claim, honesty = derive_honesty(True, None, session_digest=digest)
    assert claim == "observed_failed"
    assert honesty == "mismatch"


def test_derive_honesty_exit_code_zero_is_verified():
    digest = {"test_runs": [{"command": "pytest", "output": "3 passed", "exit_code": 0}]}
    claim, honesty = derive_honesty(True, None, session_digest=digest)
    assert claim == "observed_passed"
    assert honesty == "verified"
