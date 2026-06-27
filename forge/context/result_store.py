from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from .._lock import flock_exclusive

HANDLE = re.compile(r"^fr_[0-9a-f]{32}$")

_COMPACT_LINE_THRESHOLD = 200


class ToolResultStore:
    def __init__(self, root: Path, per_call_limit: int = 16_000, per_handle_budget: int = 32_000) -> None:
        self.root = root
        self.index = root / "index.jsonl"
        self.root.mkdir(parents=True, exist_ok=True)
        self.per_call_limit = per_call_limit
        self.per_handle_budget = per_handle_budget
        self._expanded: dict[str, int] = {}

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

    def _compact_index(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        meta: list[dict[str, Any]] = []
        expansion_totals: dict[str, int] = {}
        for entry in lines:
            if "path" in entry:
                meta.append(entry)
            else:
                h = entry.get("handle", "")
                if h:
                    existing = expansion_totals.get(h, 0)
                    if entry.get("kind") == "expansion_summary":
                        existing = max(existing, int(entry.get("total_chars", 0)))
                    else:
                        existing += int(entry.get("chars", 0))
                    expansion_totals[h] = existing
        for handle, total in sorted(expansion_totals.items()):
            meta.append({"schema_version": 1, "kind": "expansion_summary",
                         "handle": handle, "total_chars": total})
        return meta

    def _record_expansion(self, handle: str, chars: int) -> int:
        with self.index.open("a+", encoding="utf-8") as stream:
            flock_exclusive(stream)
            stream.seek(0)
            all_lines: list[dict[str, Any]] = []
            for line in stream.read().splitlines():
                try:
                    all_lines.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            consumed = 0
            for entry in all_lines:
                if entry.get("handle") != handle:
                    continue
                kind = entry.get("kind", "")
                if kind == "expansion":
                    consumed += int(entry.get("chars", 0))
                elif kind == "expansion_summary":
                    consumed = int(entry.get("total_chars", 0))
            if chars > 0:
                all_lines.append({"schema_version": 1, "kind": "expansion",
                                  "handle": handle, "chars": chars})
                if len(all_lines) >= _COMPACT_LINE_THRESHOLD:
                    all_lines = self._compact_index(all_lines)
                    stream.seek(0)
                    stream.truncate()
                    stream.write("\n".join(
                        json.dumps(e, sort_keys=True, separators=(",", ":"))
                        for e in all_lines) + ("\n" if all_lines else ""))
                else:
                    stream.seek(0, os.SEEK_END)
                    stream.write(json.dumps({"schema_version": 1, "kind": "expansion",
                                             "handle": handle, "chars": chars},
                                            sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return consumed

    def expand(self, task_id: str, handle: str, start: int = 0, max_chars: int = 16_000) -> dict[str, Any]:
        metadata = self._metadata(handle)
        if metadata.get("task_id") != task_id:
            raise PermissionError("tool-result handle belongs to another task")
        if start < 0 or max_chars <= 0 or max_chars > self.per_call_limit:
            raise ValueError("invalid expansion bounds")
        consumed = max(self._expanded.get(handle, 0), self._record_expansion(handle, 0))
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
