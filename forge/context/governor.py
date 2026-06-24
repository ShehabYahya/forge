from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable

from .formatter import estimate_tokens
from .result_store import ToolResultStore


class GovernorMode(str, Enum):
    OFF = "off"
    REPORT = "report"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class GovernorCapabilities:
    can_block_before: bool = False
    can_replace_output: bool = False
    can_request_confirmation: bool = False


DANGEROUS = (
    re.compile(r"(^|\s)rm\s+(-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\b"),
    re.compile(r"\bgit\s+(reset\s+--hard|clean\s+-[^\s]*f|push\s+.*--force)\b"),
    re.compile(r"\b(?:sudo|mkfs|shutdown|reboot)\b"),
)


def fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
    wire = json.dumps({"tool": tool_name.strip().lower(), "arguments": arguments},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(wire.encode()).hexdigest()


class ContextGovernor:
    def __init__(self, mode: GovernorMode | str, repo_root: Path, result_store: ToolResultStore,
                 capabilities: GovernorCapabilities | None = None,
                 clock: Callable[[], float] = time.time, duplicate_count: int = 16,
                 duplicate_seconds: float = 60, large_output_tokens: int = 2000) -> None:
        self.mode = GovernorMode(mode)
        self.repo_root = repo_root.resolve()
        self.result_store = result_store
        self.capabilities = capabilities or GovernorCapabilities()
        self.clock = clock
        self.duplicate_count = duplicate_count
        self.duplicate_seconds = duplicate_seconds
        self.large_output_tokens = large_output_tokens
        self._recent: deque[tuple[float, str]] = deque()

    def before(self, task_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not task_id or not tool_name or not isinstance(arguments, dict):
            return self._decision("block", "invalid governor input", needs="can_block_before")
        if self.mode is GovernorMode.OFF:
            return self._decision("allow", "governor is off")
        now = self.clock()
        key = fingerprint(tool_name, arguments)
        while self._recent and (len(self._recent) >= self.duplicate_count or now - self._recent[0][0] > self.duplicate_seconds):
            self._recent.popleft()
        duplicate = any(existing == key for _, existing in self._recent)
        self._recent.append((now, key))
        if duplicate:
            action = "block" if self.mode is GovernorMode.ACTIVE else "warn"
            return self._decision(action, "exact duplicate tool call", needs="can_block_before")
        command = str(arguments.get("command", arguments.get("cmd", "")))
        if any(pattern.search(command) for pattern in DANGEROUS):
            return self._decision("escalate" if self.mode is GovernorMode.ACTIVE else "warn",
                                  "dangerous command requires user confirmation",
                                  needs="can_request_confirmation")
        unsafe = self._unsafe_paths(arguments)
        if unsafe:
            return self._decision("escalate" if self.mode is GovernorMode.ACTIVE else "warn",
                                  "path is outside the controlled repository: " + unsafe[0],
                                  needs="can_request_confirmation")
        return self._decision("allow", "no policy concern detected")

    def after(self, task_id: str, tool_name: str, output: str) -> dict[str, Any]:
        if not isinstance(output, str):
            return self._decision("warn", "tool output was not text")
        if self.mode is GovernorMode.OFF or estimate_tokens(output) <= self.large_output_tokens:
            return self._decision("allow", "output is within limit")
        if self.mode is GovernorMode.REPORT:
            return self._decision("warn", "large tool output detected")
        if not self.capabilities.can_replace_output:
            return self._decision("warn", "large output cannot be replaced by this adapter",
                                  capability_limited=True)
        handle = self.result_store.store(task_id, output)
        replacement = f"Large output stored as {handle}. Use forge_expand_tool_result with this task id."
        return self._decision("replace", "large output stored for bounded expansion",
                              replacement_output=replacement, handle=handle)

    def _unsafe_paths(self, value: Any) -> list[str]:
        found: list[str] = []
        path_keys = {"path", "file", "filename", "filepath", "cwd", "directory", "destination", "target"}

        def visit(item: Any, key: str = "") -> None:
            if isinstance(item, dict):
                for child_key, child in item.items():
                    visit(child, str(child_key).lower())
            elif isinstance(item, list):
                for child in item:
                    visit(child, key)
            elif isinstance(item, str) and key in path_keys:
                candidate = Path(item)
                target = candidate if candidate.is_absolute() else self.repo_root / candidate
                try:
                    resolved = target.resolve(strict=False)
                    if not resolved.is_relative_to(self.repo_root):
                        found.append(item)
                    elif target.exists() and target.resolve(strict=True).is_relative_to(self.repo_root) is False:
                        found.append(item)
                except (OSError, ValueError):
                    found.append(item)

        visit(value)
        return found

    def _decision(self, decision: str, reason: str, needs: str | None = None,
                  capability_limited: bool = False, **extra: Any) -> dict[str, Any]:
        if self.mode is GovernorMode.REPORT and decision not in {"allow", "warn"}:
            decision = "warn"
        if self.mode is GovernorMode.ACTIVE and needs and not getattr(self.capabilities, needs):
            capability_limited = True
            decision = "warn"
            reason += f"; adapter lacks {needs}"
        return {"schema_version": 1, "ok": True, "decision": decision, "reason": reason,
                "replacement_output": extra.pop("replacement_output", None),
                "capability_limited": capability_limited, **extra}

