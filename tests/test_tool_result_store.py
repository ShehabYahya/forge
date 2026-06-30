import hashlib
import json
import os
import secrets
from pathlib import Path

import pytest

from forge._lock import flock_exclusive
from forge.context.result_store import HANDLE, ToolResultStore


def _store(root: Path, task_id: str, content: str) -> str:
    """Write tool-result data directly to disk (replaces removed store() method)."""
    root.mkdir(parents=True, exist_ok=True)
    handle = "fr_" + secrets.token_hex(16)
    raw = root / f"{handle}.raw"
    sha = hashlib.sha256(content.encode()).hexdigest()
    raw.write_text(content, encoding="utf-8")
    metadata = {"schema_version": 1, "handle": handle, "task_id": task_id,
                "path": raw.name, "chars": len(content), "sha256": sha}
    index = root / "index.jsonl"
    with index.open("a", encoding="utf-8") as stream:
        flock_exclusive(stream)
        stream.write(json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return handle


def test_persistence_ownership_redaction_and_bounds(tmp_path):
    root = tmp_path / "results"
    handle = _store(root, "task-a", "api_key=supersecret\n" + "x" * 100)
    raw_path = root / f"{handle}.raw"
    assert raw_path.read_text() == "api_key=supersecret\n" + "x" * 100
    store = ToolResultStore(root, per_call_limit=20, per_handle_budget=25)
    with pytest.raises(PermissionError):
        store.expand("task-b", handle, 0, 10)
    assert len(store.expand("task-a", handle, 0, 20)["content"]) == 20
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
    handle = _store(tmp_path, "task", "content")
    text = store.index.read_text().replace(f"{handle}.raw", "other.raw")
    store.index.write_text(text)
    with pytest.raises(ValueError):
        store.expand("task", handle)
