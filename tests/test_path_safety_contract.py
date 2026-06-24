from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from forge.context.governor import ContextGovernor, GovernorCapabilities
from forge.context.result_store import ToolResultStore
from forge.review.diff import RepositoryInspectionError, safe_path

IS_WIN32 = sys.platform == "win32"
_FIXTURE = files("forge").joinpath("plugin/opencode/path_safety_cases.json")


def _load_cases() -> list[dict[str, Any]]:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return [c for c in data if isinstance(c, dict) and "id" in c]


def _substitute(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        for placeholder, real in mapping.items():
            value = value.replace(placeholder, real)
        return value
    if isinstance(value, dict):
        return {k: _substitute(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, mapping) for v in value]
    return value


def _build_setup(steps: list[dict[str, Any]], mapping: dict[str, str]) -> None:
    for step in steps:
        step_type = step["type"]
        if step_type == "symlink-tamper":
            continue
        path = Path(_substitute(step["path"], mapping))
        if step_type == "dir":
            path.mkdir(parents=True, exist_ok=True)
        elif step_type == "file":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("data\n", encoding="utf-8")
        elif step_type == "symlink":
            target = _substitute(step["target"], mapping)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.exists():
                path.unlink()
            path.symlink_to(target)


def _params() -> list[Any]:
    params: list[Any] = []
    for case in _load_cases():
        marks: list[pytest.MarkDecorator] = []
        platform = case.get("platform")
        if platform is not None:
            if "win32" in platform and not IS_WIN32:
                marks.append(pytest.mark.skip(reason="win32-only path-separator case"))
            elif "posix" in platform and IS_WIN32:
                marks.append(pytest.mark.skip(reason="posix-only path-separator case"))
        params.append(pytest.param(case, id=case["id"], marks=marks))
    return params


def _check_governor(governor: ContextGovernor, key: str, value: Any) -> bool:
    return len(governor._unsafe_paths({key: value})) > 0


def _check_safe_path(repo: Path, value: str) -> bool:
    try:
        safe_path(repo, value)
        return False
    except RepositoryInspectionError:
        return True


def _check_result_store(store: ToolResultStore, case: dict[str, Any],
                        value: Any, outside: Path) -> bool:
    has_tamper = any(s.get("type") == "symlink-tamper" for s in case.get("setup", []))
    if has_tamper:
        store.root.mkdir(parents=True, exist_ok=True)
        handle = "fr_" + secrets.token_hex(16)
        raw_path = store.root / f"{handle}.raw"
        raw_path.write_text("real content\n", encoding="utf-8")
        sha = hashlib.sha256(b"real content\n").hexdigest()
        metadata = {"schema_version": 1, "handle": handle, "task_id": "task",
                    "path": raw_path.name, "chars": 13, "sha256": sha}
        with store.index.open("a", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            json.dump(metadata, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        secret = outside / "secret.txt"
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_text("secret\n", encoding="utf-8")
        raw_path.unlink()
        raw_path.symlink_to(secret)
        handle_value = handle
    else:
        handle_value = value
    try:
        store.expand("task", handle_value, 0, 16000)
        return False
    except (ValueError, KeyError, PermissionError):
        return True


@pytest.mark.parametrize("case", _params())
def test_path_safety_contract(case: dict[str, Any], tmp_path: Path, repo: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    mapping = {
        "@REPO@": str(repo),
        "@OUTSIDE@": str(outside),
        "@SCRATCH@": str(scratch),
    }
    _build_setup(case.get("setup", []), mapping)
    value = _substitute(case["value"], mapping)
    expect_unsafe = case["expect"] == "unsafe"

    if case["contract"] == "governor":
        governor = ContextGovernor(
            "active", repo,
            GovernorCapabilities(can_request_confirmation=True),
            clock=lambda: 0.0,
        )
        detected = _check_governor(governor, case["key"], value)
    elif case["contract"] == "safe_path":
        detected = _check_safe_path(repo, value)
    else:
        store = ToolResultStore(scratch / "results")
        detected = _check_result_store(store, case, value, outside)

    assert detected == expect_unsafe, (
        f"{case['id']}: expected {'unsafe' if expect_unsafe else 'allow'} but got "
        f"{'unsafe' if detected else 'allow'}"
    )


def test_governor_before_dotdot_escalates_in_active_mode(tmp_path: Path, repo: Path) -> None:
    governor = ContextGovernor(
        "active", repo,
        GovernorCapabilities(can_request_confirmation=True),
        clock=lambda: 0.0,
    )
    decision = governor.before("task", "write", {"path": "../outside"})
    assert decision["decision"] == "escalate"


def test_governor_before_normal_relative_allows(tmp_path: Path, repo: Path) -> None:
    governor = ContextGovernor(
        "active", repo,
        GovernorCapabilities(can_request_confirmation=True),
        clock=lambda: 0.0,
    )
    decision = governor.before("task", "write", {"path": "src/app.ts"})
    assert decision["decision"] == "allow"
