from __future__ import annotations

import argparse
from typing import Any

from mcp.server.fastmcp import FastMCP

from .service import ForgeService

PUBLIC_TOOLS = (
    "start_task",
    "review_changes",
    "finish_task",
    "submit_outcome",
    "expand_tool_result",
)

mcp = FastMCP("forge")
_service = ForgeService()


@mcp.tool()
def start_task(task_text: str, repo_root: str, expected_files: list[str] | None = None,
               host_session_id: str | None = None, replace_active: bool = False) -> dict[str, Any]:
    """Start a task and return all prepared context."""
    return _service.start_task(task_text, repo_root, expected_files, host_session_id, replace_active)


@mcp.tool()
def review_changes(task_id: str, validation_evidence: list[dict[str, Any]] | None = None,
                   remaining_uncertainty: str | None = None,
                   agent_step_intent: str | None = None,
                   target_behavior_claim: str | None = None,
                   owner_boundary_claim: str | None = None,
                   proof_plan: str | None = None) -> dict[str, Any]:
    """Review the repository's observed Git changes."""
    return _service.review_changes(
        task_id, validation_evidence, remaining_uncertainty,
        agent_step_intent, target_behavior_claim, owner_boundary_claim, proof_plan)


@mcp.tool()
def finish_task(task_id: str, success: bool, summary: str,
                validation_evidence: list[dict[str, Any]] | None = None,
                remaining_issues: list[str] | None = None,
                commands_run: list[str] | None = None,
                memory_draft: dict | None = None,
                memory_feedback: list[dict] | None = None) -> dict[str, Any]:
    """Finish normally; successful completion requires a fresh passing review."""
    return _service.finish_task(
        task_id, success, summary, validation_evidence, remaining_issues,
        commands_run, memory_draft, memory_feedback)


@mcp.tool()
def submit_outcome(success: bool, summary: str, degraded_reason: str,
                   task_id: str | None = None, repo_root: str | None = None) -> dict[str, Any]:
    """Record an explicitly degraded, unverified fallback outcome."""
    return _service.submit_outcome(success, summary, degraded_reason, task_id, repo_root)


@mcp.tool()
def expand_tool_result(task_id: str, handle: str, start: int = 0,
                       max_chars: int = 16_000) -> dict[str, Any]:
    """Expand a bounded slice of a task-owned stored tool result."""
    return _service.expand_tool_result(task_id, handle, start, max_chars)


def run_mcp() -> None:
    mcp.run(transport="stdio")


def main() -> None:
    parser = argparse.ArgumentParser(description="Forge MCP stdio server")
    parser.parse_args()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
