from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from .service import ForgeService

PUBLIC_TOOLS = (
    "forge_start_task",
    "forge_review_changes",
    "forge_finish_task",
    "forge_submit_outcome",
    "forge_expand_tool_result",
)

mcp = FastMCP("forge-alpha")
_service = ForgeService()


@mcp.tool()
def forge_start_task(task_text: str, repo_root: str, expected_files: list[str] | None = None,
                     host_session_id: str | None = None, replace_active: bool = False) -> dict[str, Any]:
    """Start a task and return all prepared context."""
    return _service.forge_start_task(task_text, repo_root, expected_files, host_session_id, replace_active)


@mcp.tool()
def forge_review_changes(task_id: str, validation_evidence: list[dict[str, Any]] | None = None,
                         remaining_uncertainty: str | None = None) -> dict[str, Any]:
    """Review the repository's observed Git changes."""
    return _service.forge_review_changes(task_id, validation_evidence, remaining_uncertainty)


@mcp.tool()
def forge_finish_task(task_id: str, success: bool, summary: str,
                      validation_evidence: list[dict[str, Any]] | None = None,
                      remaining_issues: list[str] | None = None) -> dict[str, Any]:
    """Finish normally; successful completion requires a fresh passing review."""
    return _service.forge_finish_task(task_id, success, summary, validation_evidence, remaining_issues)


@mcp.tool()
def forge_submit_outcome(success: bool, summary: str, degraded_reason: str,
                         task_id: str | None = None, repo_root: str | None = None) -> dict[str, Any]:
    """Record an explicitly degraded, unverified fallback outcome."""
    return _service.forge_submit_outcome(success, summary, degraded_reason, task_id, repo_root)


@mcp.tool()
def forge_expand_tool_result(task_id: str, handle: str, start: int = 0,
                             max_chars: int = 16_000) -> dict[str, Any]:
    """Expand a bounded slice of a task-owned stored tool result."""
    return _service.forge_expand_tool_result(task_id, handle, start, max_chars)


def main() -> None:
    parser = argparse.ArgumentParser(description="Forge Alpha MCP stdio server")
    parser.parse_args()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
