"""Generate (or verify) the TypeScript forge-system module from the canonical
Markdown operating prompt at docs/Forge Native Operating.md.

Usage:
  python scripts/generate_forge_system.py          # write forge-system.ts
  python scripts/generate_forge_system.py --check  # fail if stale
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = REPO_ROOT / "docs" / "Forge Native Operating.md"
TS_PATH = REPO_ROOT / "forge" / "plugin" / "opencode" / "src" / "forge-system.ts"

HEADER = """\
// Auto-generated source for the Forge system bootstrap prompt.
//
// The prompt text is the verbatim contents of
//   docs/Forge Native Operating.md
// Do not summarize, rewrite, or "improve" it here. To update the prompt, update
// that document and regenerate this file (or paste the new text verbatim).
//
// The surrounding <forge_system>...</forge_system> wrapper is added by code in
// forgeSystemBlock() so the document remains usable outside OpenCode.

"""


def _escape_ts(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _format_prompt_body(raw: str) -> str:
    lines = raw.rstrip("\n").split("\n")
    max_len = 0
    for line in lines:
        escaped = _escape_ts(line)
        if len(escaped) > max_len:
            max_len = len(escaped)
    escaped_lines = [_escape_ts(line) for line in lines]
    result_parts: list[str] = []
    for i, escaped in enumerate(escaped_lines):
        if i == len(escaped_lines) - 1:
            result_parts.append(f'"{escaped}"')
        else:
            result_parts.append(f'"{escaped}\\n"')
    return " +\n".join(result_parts)


def generate() -> str:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    body = _format_prompt_body(prompt)
    return f"""{HEADER}/**
 * Marker tag used to deduplicate Forge system-prompt injection. Must never
 * appear inside FORGE_SYSTEM_BOOTSTRAP itself.
 */
export const FORGE_SYSTEM_MARKER_OPEN = "<forge_system>";
export const FORGE_SYSTEM_MARKER_CLOSE = "</forge_system>";

/**
 * Static Forge bootstrap operating protocol. Injected at OpenCode's
 * first-class system-prompt layer when Forge MCP is connected. This is an
 * operating protocol, not task state; it is safe to inject before any
 * forge_start_task call.
 */
export const FORGE_SYSTEM_BOOTSTRAP = {body};

/**
 * Wrap the bootstrap prompt in <forge_system>...</forge_system>. This wrapper
 * is added by code (not present in the source document) so the document stays
 * usable outside OpenCode.
 */
export function forgeSystemBlock(): string {{
  return FORGE_SYSTEM_MARKER_OPEN + "\\n" + FORGE_SYSTEM_BOOTSTRAP + "\\n" + FORGE_SYSTEM_MARKER_CLOSE;
}}

/**
 * True if the given system-prompt text already contains the Forge marker,
 * used to prevent duplicate injection.
 */
export function hasForgeSystemMarker(text: string): boolean {{
  return text.includes(FORGE_SYSTEM_MARKER_OPEN);
}}
"""


def main() -> None:
    check_only = "--check" in sys.argv
    generated = generate()
    current = TS_PATH.read_text(encoding="utf-8") if TS_PATH.exists() else ""
    if current == generated:
        return
    if check_only:
        diff = "\n".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                fromfile=str(TS_PATH),
                tofile="(generated)",
            )
        )
        print(diff, file=sys.stderr)
        print(
            f"error: {TS_PATH} is stale; regenerate with scripts/generate_forge_system.py",
            file=sys.stderr,
        )
        sys.exit(1)
    TS_PATH.write_text(generated, encoding="utf-8")
    print(f"wrote {TS_PATH}")


if __name__ == "__main__":
    main()
