from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any

import fcntl

HANDLE = re.compile(r"^fr_[0-9a-f]{32}$")
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(https?://[^:/\s]+:)[^@/\s]+@"),
]


def redact(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(1) + (match.group(2) if match.lastindex == 2 else "") + "[REDACTED]", redacted)
    return redacted


class ToolResultStore:
    def __init__(self, root: Path, per_call_limit: int = 16_000, per_handle_budget: int = 32_000) -> None:
        self.root = root
        self.index = root / "index.jsonl"
        self.per_call_limit = per_call_limit
        self.per_handle_budget = per_handle_budget
        self._expanded: dict[str, int] = {}

    def store(self, task_id: str, content: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        handle = "fr_" + secrets.token_hex(16)
        raw = self.root / f"{handle}.raw"
        sanitized = redact(content)
        raw.write_text(sanitized, encoding="utf-8")
        metadata = {"schema_version": 1, "handle": handle, "task_id": task_id,
                    "path": raw.name, "chars": len(sanitized),
                    "sha256": hashlib.sha256(sanitized.encode()).hexdigest()}
        with self.index.open("a", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return handle

    def _metadata(self, handle: str) -> dict[str, Any]:
        if not HANDLE.fullmatch(handle) or any(value in handle for value in ("/", "\\", "..", "\0")):
            raise ValueError("malformed tool-result handle")
        found = None
        if self.index.exists():
            for line in self.index.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                    if value.get("handle") == handle and "path" in value:
                        found = value
                except json.JSONDecodeError:
                    continue
        if not found:
            raise KeyError("unknown tool-result handle")
        if found.get("path") != f"{handle}.raw":
            raise ValueError("tool-result metadata path mismatch")
        return found

    def _consumed_from_index(self, handle: str) -> int:
        consumed = 0
        if self.index.exists():
            for line in self.index.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                    if value.get("kind") == "expansion" and value.get("handle") == handle:
                        consumed += int(value.get("chars", 0))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
        return consumed

    def _record_expansion(self, handle: str, chars: int) -> None:
        with self.index.open("a", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(json.dumps({"schema_version": 1, "kind": "expansion", "handle": handle,
                                     "chars": chars}, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def expand(self, task_id: str, handle: str, start: int = 0, max_chars: int = 16_000) -> dict[str, Any]:
        metadata = self._metadata(handle)
        if metadata.get("task_id") != task_id:
            raise PermissionError("tool-result handle belongs to another task")
        if start < 0 or max_chars <= 0 or max_chars > self.per_call_limit:
            raise ValueError("invalid expansion bounds")
        consumed = max(self._expanded.get(handle, 0), self._consumed_from_index(handle))
        allowed = min(max_chars, self.per_handle_budget - consumed)
        if allowed <= 0:
            raise ValueError("tool-result expansion budget exhausted")
        path = self.root / metadata["path"]
        if path.is_symlink() or path.resolve(strict=True).parent != self.root.resolve(strict=True):
            raise ValueError("unsafe tool-result path")
        content = path.read_text(encoding="utf-8")
        chunk = content[start:start + allowed]
        self._expanded[handle] = consumed + len(chunk)
        self._record_expansion(handle, len(chunk))
        return {"handle": handle, "start": start, "content": chunk,
                "next_start": start + len(chunk), "complete": start + len(chunk) >= len(content)}
