from pathlib import Path


REQUIRED = {"schema_version", "ok", "task_id", "state", "warnings", "required_next_action"}


def test_every_response_has_envelope(service, repo):
    responses = [
        service.forge_start_task("", str(repo)),
        service.forge_start_task("task", str(repo)),
        service.forge_review_changes("missing"),
        service.forge_finish_task("missing", False, "x"),
        service.forge_submit_outcome(False, "x", "reason", task_id="missing"),
        service.forge_expand_tool_result("missing", "fr_" + "0" * 32),
    ]
    assert all(REQUIRED <= result.keys() for result in responses)


def test_invalid_repository_and_escaping_expected_path_rejected(service, tmp_path, repo):
    assert not service.forge_start_task("task", str(tmp_path / "missing"))["ok"]
    result = service.forge_start_task("task", str(repo), ["../escape"])
    assert not result["ok"] and "escapes" in result["error"]


def test_bound_session_is_idempotent_unless_replaced(tmp_path, repo):
    from forge.service import ForgeService
    ids = iter(["one", "two"])
    service = ForgeService(tmp_path / "runtime", clock=lambda: 1, id_factory=lambda seed: next(ids))
    first = service.forge_start_task("first", str(repo), host_session_id="session")
    same = service.forge_start_task("second", str(repo), host_session_id="session")
    assert same["task_id"] == first["task_id"] and same["idempotent"]
    replacement = service.forge_start_task("second", str(repo), host_session_id="session", replace_active=True)
    assert replacement["task_id"] == "two"

