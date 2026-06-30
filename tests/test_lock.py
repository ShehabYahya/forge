from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

import forge._lock as lock_mod
from forge._lock import flock_exclusive, flock_shared


def test_flock_exclusive_does_not_crash(tmp_path):
    lock_file = tmp_path / "test.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+", encoding="utf-8") as f:
        flock_exclusive(f)


def test_flock_shared_does_not_crash(tmp_path):
    lock_file = tmp_path / "test_shared.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+", encoding="utf-8") as f:
        flock_shared(f)


def test_degraded_mode_warns_once(tmp_path, monkeypatch):
    monkeypatch.setattr(lock_mod, "portalocker", None)
    monkeypatch.setattr(lock_mod, "fcntl", None)
    monkeypatch.setattr(lock_mod, "_degraded_warned", False)
    lock_file = tmp_path / "degraded.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+", encoding="utf-8") as f:
        with pytest.warns(UserWarning, match="degraded"):
            flock_exclusive(f)
    with lock_file.open("a+", encoding="utf-8") as f:
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            flock_exclusive(f)
            assert len(w) == 0


def test_shared_falls_back_to_exclusive_on_oserror(tmp_path, monkeypatch):
    fake_portalocker = mock.MagicMock()
    fake_portalocker.LOCK_SH = 1
    fake_portalocker.LOCK_EX = 2
    fake_portalocker.lock = mock.MagicMock(
        side_effect=[OSError("shared not supported"), None])
    monkeypatch.setattr(lock_mod, "portalocker", fake_portalocker)
    lock_file = tmp_path / "fallback.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with lock_file.open("a+", encoding="utf-8") as f:
        flock_shared(f)
    assert fake_portalocker.lock.call_count == 2
    assert fake_portalocker.lock.call_args_list[1][0][1] == fake_portalocker.LOCK_EX


def test_multi_process_exclusive_serializes(tmp_path):
    import multiprocessing as mp

    counter_file = tmp_path / "counter.json"
    lock_file = tmp_path / "mp.lock"
    counter_file.write_text(json.dumps({"value": 0}))

    def _worker(lock_path: str, counter_path: str, results_path: str) -> None:
        with open(lock_path, "a+", encoding="utf-8") as lf:
            flock_exclusive(lf)
            import time
            data = json.loads(Path(counter_path).read_text())
            current = data["value"]
            time.sleep(0.05)
            data["value"] = current + 1
            Path(counter_path).write_text(json.dumps(data))
            Path(results_path).write_text(f"done:{current}\n")

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    procs = []
    for i in range(3):
        r = results_dir / f"r{i}.txt"
        p = mp.Process(target=_worker, args=(str(lock_file), str(counter_file), str(r)))
        p.start()
        procs.append(p)
    for p in procs:
        p.join(timeout=10)
        assert not p.is_alive(), "worker process timed out"
    final = json.loads(counter_file.read_text())
    assert final["value"] == 3


def test_import_smoke_forge_persistence():
    import forge.persistence
    assert forge.persistence is not None


def test_import_smoke_forge_telemetry_writer():
    import forge.telemetry.writer
    assert forge.telemetry.writer is not None


def test_import_smoke_forge_memory_store():
    import forge.memory.store
    assert forge.memory.store is not None


def test_import_smoke_forge_plugin_session_state():
    import forge.plugin.session_state
    assert forge.plugin.session_state is not None


def test_import_smoke_forge_context_result_store():
    import forge.context.result_store
    assert forge.context.result_store is not None


def test_no_unconditional_fcntl_in_test_suite():
    import ast
    tests_dir = Path(__file__).parent
    violations = []
    for py_file in tests_dir.glob("*.py"):
        if py_file.name == "test_lock.py":
            continue
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fcntl":
                        violations.append(str(py_file))
            elif isinstance(node, ast.ImportFrom):
                if node.module == "fcntl":
                    violations.append(str(py_file))
    assert not violations, f"Unconditional fcntl import in: {violations}"
