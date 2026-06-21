import pytest

from forge.context.result_store import ToolResultStore


def test_persistence_ownership_redaction_and_bounds(tmp_path):
    root = tmp_path / "results"
    first = ToolResultStore(root)
    handle = first.store("task-a", "api_key=supersecret\n" + "x" * 100)
    assert "supersecret" not in (root / f"{handle}.raw").read_text()
    second = ToolResultStore(root, per_call_limit=20, per_handle_budget=25)
    with pytest.raises(PermissionError):
        second.expand("task-b", handle, 0, 10)
    assert len(second.expand("task-a", handle, 0, 20)["content"]) == 20
    restarted = ToolResultStore(root, per_call_limit=20, per_handle_budget=25)
    assert len(restarted.expand("task-a", handle, 20, 20)["content"]) == 5
    with pytest.raises(ValueError):
        restarted.expand("task-a", handle, 25, 1)


@pytest.mark.parametrize("handle", ["../x", "fr_bad", "fr_" + "0" * 31, "fr_" + "0" * 32 + "/x", "fr_" + "0" * 31 + "\0"])
def test_malformed_handles_rejected(tmp_path, handle):
    with pytest.raises((ValueError, KeyError)):
        ToolResultStore(tmp_path).expand("task", handle)


def test_metadata_path_mismatch_rejected(tmp_path):
    store = ToolResultStore(tmp_path)
    handle = store.store("task", "content")
    text = store.index.read_text().replace(f"{handle}.raw", "other.raw")
    store.index.write_text(text)
    with pytest.raises(ValueError):
        store.expand("task", handle)
