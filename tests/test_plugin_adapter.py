from pathlib import Path

from forge.plugin.opencode_adapter import OpenCodeAdapter
from forge.plugin.protocol import HIDDEN_OPERATIONS, PluginProtocolBackend


def test_every_operation_forwards_normalized_input_and_returned_action():
    seen = []
    expected = {"schema_version": 1, "ok": True, "task_id": "t", "decision": "block",
                "reason": "backend", "replacement_output": None, "user_message": None,
                "capability_limited": False}
    adapter = OpenCodeAdapter(lambda wire: seen.append(wire) or expected)
    for operation in HIDDEN_OPERATIONS:
        assert adapter.forward(operation, {1: Path("x")}) is expected
    assert all(item["payload"] == {"1": "x"} for item in seen)


def test_backend_outage_is_explicitly_degraded():
    def unavailable(wire):
        raise OSError("offline")
    result = OpenCodeAdapter(unavailable).forward("get_active_task", {})
    assert not result["ok"] and result["capability_limited"]
    assert "not actively enforced" in result["user_message"]


def test_protocol_rejects_wrong_version():
    result = OpenCodeAdapter(lambda wire: {"schema_version": 2, "ok": True}).forward("get_active_task", {})
    assert not result["ok"]


def test_hidden_backend_resolves_task_and_owns_governor_decision(service, repo):
    task_id = service.forge_start_task("task", str(repo), host_session_id="host")["task_id"]
    backend = PluginProtocolBackend(service)
    resolved = backend.handle({"schema_version": 1, "operation": "get_active_task",
                               "payload": {"host_session_id": "host"}})
    assert resolved["task_id"] == task_id
    observed = backend.handle({"schema_version": 1, "operation": "observe_tool_before",
                               "payload": {"task_id": task_id, "tool_name": "read",
                                           "arguments": {"path": "base.txt"}}})
    assert observed["decision"] == "allow"


def test_plugin_source_has_no_business_rules():
    source = Path("forge/plugin/opencode/src/index.ts").read_text().lower()
    for prohibited in ("transition table", "dangerous command", "duplicate tracker", "anvil stage"):
        assert prohibited not in source
