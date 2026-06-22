from __future__ import annotations

import re

from forge.config import ValidationConfig

# Concrete-anchor detectors. Intentionally simple and deterministic: a memory
# is "generic only" when it matches the blocklist AND contains none of these
# anchors (file path, function call, module/tool/command name, etc.).

_FILE_EXT_RE = re.compile(
    r"[\w./-]+\.(?:py|ts|js|json|md|toml|yaml|yml|go|rs|java|rb|sh|txt)\b",
    re.IGNORECASE,
)
_PATH_SLASH_RE = re.compile(r"[\w.-]+/[\w./-]+")
_FUNC_CALL_RE = re.compile(r"[A-Za-z_]\w*\s*\(")
_DEF_RE = re.compile(r"\bdef\s+\w+")
_BACKTICK_RE = re.compile(r"`[^`]+`")
_CAMELCASE_RE = re.compile(r"[A-Z][a-z]+[A-Z]")
_SNAKE_CASE_RE = re.compile(r"\b[a-z]+_[a-z]+\b")
_TOOL_RE = re.compile(
    r"\b(?:pytest|git|npm|bash|uv|pip|docker|kubectl)\b"
)
_SNAKE_CASE_MIN_LEN = 4


def has_concrete_anchor(text: str) -> bool:
    """Return True if ``text`` mentions a concrete anchor.

    Anchors: a file-path-like token (extension or a ``/`` path segment), a
    function-like token (``foo()``, ``def foo``, backticked token), or a
    module/command/tool name (CamelCase, snake_case of length >= 4, or a
    known command keyword). Kept deliberately simple; no NLP.
    """
    if not isinstance(text, str) or not text:
        return False
    if _FILE_EXT_RE.search(text) or _PATH_SLASH_RE.search(text):
        return True
    if _FUNC_CALL_RE.search(text) or _DEF_RE.search(text) or _BACKTICK_RE.search(text):
        return True
    if _CAMELCASE_RE.search(text) or _TOOL_RE.search(text):
        return True
    for match in _SNAKE_CASE_RE.finditer(text):
        if len(match.group(0)) >= _SNAKE_CASE_MIN_LEN:
            return True
    return False


def is_generic_only(memory: str, config: ValidationConfig) -> bool:
    """True if ``memory`` matches a blocklist phrase AND has no concrete anchor."""
    if not isinstance(memory, str) or not memory:
        return False
    lowered = memory.lower()
    if not any(phrase.lower() in lowered for phrase in config.generic_blocklist):
        return False
    return not has_concrete_anchor(memory)


def validate_memory_text(memory: str, config: ValidationConfig) -> str | None:
    """Validate a memory draft. Return ``None`` if valid, else a reason string.

    Checks: non-empty string; length within ``[memory_min_chars,
    memory_max_chars]``; not generic-only (blocklist match without a concrete
    anchor).
    """
    if not isinstance(memory, str) or not memory.strip():
        return "memory is required and must be non-empty text"
    length = len(memory)
    if length < config.memory_min_chars:
        return f"memory must be at least {config.memory_min_chars} chars (got {length})"
    if length > config.memory_max_chars:
        return f"memory must be at most {config.memory_max_chars} chars (got {length})"
    if is_generic_only(memory, config):
        lowered = memory.lower()
        phrase = next(p for p in config.generic_blocklist if p.lower() in lowered)
        return f"memory too generic: matched '{phrase}' without concrete anchor"
    return None


def validate_why(why: str | None, config: ValidationConfig) -> str | None:
    """Validate the optional ``why`` field. ``None``/empty -> valid (``None``)."""
    if why is None:
        return None
    if not isinstance(why, str):
        return "why must be a string or None"
    if not why.strip():
        return None
    length = len(why)
    if length < config.why_min_chars:
        return f"why must be at least {config.why_min_chars} chars (got {length})"
    return None


def normalize_memory_text(text: str) -> str:
    """Lowercase + collapse all whitespace runs to single spaces + strip.

    Used for cross-task duplicate/pattern detection. Non-string input yields "".
    """
    if not isinstance(text, str):
        return ""
    return " ".join(text.lower().split())
