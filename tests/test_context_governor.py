from forge.context.formatter import estimate_tokens
from forge.context.governor import ContextGovernor, GovernorCapabilities, fingerprint
from forge.context.result_store import ToolResultStore


def test_token_estimation_boundaries():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_fingerprint_is_stable_across_dictionary_order():
    assert fingerprint("Shell", {"b": 2, "a": 1}) == fingerprint("shell", {"a": 1, "b": 2})
    assert fingerprint("shell", {"a": 1}) != fingerprint("shell", {"a": 2})


def test_duplicate_modes_and_window(tmp_path, repo):
    times = iter([0, 1, 100])
    governor = ContextGovernor("active", repo, ToolResultStore(tmp_path / "results"),
                               GovernorCapabilities(can_block_before=True), clock=lambda: next(times))
    assert governor.before("task", "read", {"path": "base.txt"})["decision"] == "allow"
    assert governor.before("task", "read", {"path": "base.txt"})["decision"] == "block"
    assert governor.before("task", "read", {"path": "base.txt"})["decision"] == "allow"


def test_dangerous_command_escalates_only_with_capability(tmp_path, repo):
    limited = ContextGovernor("active", repo, ToolResultStore(tmp_path / "a"))
    result = limited.before("task", "shell", {"command": "rm -rf build"})
    assert result["decision"] == "warn" and result["capability_limited"]
    capable = ContextGovernor("active", repo, ToolResultStore(tmp_path / "b"),
                              GovernorCapabilities(can_request_confirmation=True))
    assert capable.before("task", "shell", {"command": "rm -rf build"})["decision"] == "escalate"
    assert capable.before("task", "shell", {"command": "ls build"})["decision"] == "allow"


def test_out_of_repo_path_and_large_output_capabilities(tmp_path, repo):
    store = ToolResultStore(tmp_path / "results")
    governor = ContextGovernor("report", repo, store)
    assert governor.before("task", "write", {"path": "../outside"})["decision"] == "warn"
    assert governor.after("task", "shell", "x" * 8001)["decision"] == "warn"
    active = ContextGovernor("active", repo, store, GovernorCapabilities(can_replace_output=True))
    result = active.after("task", "shell", "x" * 8001)
    assert result["decision"] == "replace" and result["handle"].startswith("fr_")


def test_off_mode_allows_valid_input(tmp_path, repo):
    governor = ContextGovernor("off", repo, ToolResultStore(tmp_path / "results"))
    assert governor.before("task", "shell", {"command": "rm -rf /"})["decision"] == "allow"

