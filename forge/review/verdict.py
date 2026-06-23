from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
import ast
from typing import Any, Callable

from .baseline import capture_tree, diff_trees
from .diff import RepositoryInspectionError, capture_changes, digest_changes
from .evidence import classify_evidence

def _tree_exists(repo: Path, tree_id: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", tree_id],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False,
    )
    return result.returncode == 0 and result.stdout.strip() == b"tree"


def _fail(repo_inspect_error: str, evidence: list[dict[str, Any]] | None,
          clock: Callable[[], float],
          agent_step_intent: str | None,
          target_behavior_claim: str | None,
          owner_boundary_claim: str | None,
          proof_plan: str | None) -> dict[str, Any]:
    return {"passed": False, "blockers": [f"repository cannot be inspected: {repo_inspect_error}"],
            "warnings": [], "changed_files": [], "diff_digest": None,
            "task_changed_files": [], "task_diff_digest": None,
            "preexisting_dirty_files": [], "total_worktree_changed_files": [],
            "baseline_tree_id": None, "current_tree_id": None,
            "unexplained_changed_files": [], "mutation_ledger_summary": None,
            "evidence_status": classify_evidence(evidence), "ready_to_finish": False,
            "reviewed_at": _timestamp(clock()),
            "semantic_correctness_observed": False,
            "agent_step_intent": agent_step_intent,
            "target_behavior_claim": target_behavior_claim,
            "owner_boundary_claim": owner_boundary_claim,
            "proof_plan": proof_plan}


def review_repository(repo: Path, expected_files: list[str], scope_mode: str,
                      evidence: list[dict[str, Any]] | None, uncertainty: str | None,
                      clock: Callable[[], float], *,
                      agent_step_intent: str | None = None,
                      target_behavior_claim: str | None = None,
                      owner_boundary_claim: str | None = None,
                      proof_plan: str | None = None,
                      baseline_tree_id: str | None = None) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    baseline_available = bool(baseline_tree_id)
    current_tree_id: str | None = None
    task_changes: list = []
    preexisting_changes: list = []

    # ---------- total-worktree diff (backward-compat source of truth) --------
    try:
        total_changes = capture_changes(repo)
    except RepositoryInspectionError as exc:
        return _fail(str(exc), evidence, clock,
                     agent_step_intent, target_behavior_claim,
                     owner_boundary_claim, proof_plan)

    # ---------- baseline-aware deltas ----------------------------------------
    if baseline_available:
        repo_path = repo
        try:
            assert baseline_tree_id is not None
            if not _tree_exists(repo_path, baseline_tree_id):
                warnings.append("baseline tree object no longer exists; "
                                "task delta cannot be isolated from pre-existing changes")
                baseline_available = False
        except Exception:
            warnings.append("baseline tree validation failed; "
                            "task delta cannot be isolated")
            baseline_available = False

    if baseline_available:
        try:
            assert baseline_tree_id is not None
            current_tree_id = capture_tree(repo)
            task_changes = diff_trees(repo, baseline_tree_id, current_tree_id)
            try:
                preexisting_changes = diff_trees(repo, "HEAD", baseline_tree_id)
            except (RepositoryInspectionError, subprocess.CalledProcessError):
                # HEAD may not exist; leave preexisting empty.
                pass
        except RepositoryInspectionError as exc:
            warnings.append(f"baseline-aware delta failed ({exc}); "
                            "falling back to total-worktree diff")
            baseline_available = False

    # ---------- scope and blocker rules use TASK delta -----------------------
    if not baseline_available:
        task_changes = total_changes
        current_tree_id = None

    task_changed_files = [item.path for item in task_changes]
    total_changed_files = [item.path for item in total_changes]
    preexisting_dirty_files = [item.path for item in preexisting_changes]

    # No-change blocker: uses task delta.
    if not task_changes:
        blockers.append("no changes found for implementation task")

    # Scope check: uses task delta.
    task_unexpected = sorted(set(task_changed_files) - set(expected_files)) if expected_files else []
    if task_unexpected and scope_mode == "strict":
        blockers.append("changed files outside strict expected scope: " + ", ".join(task_unexpected))
    elif task_unexpected:
        warnings.append("changed files outside expected scope: " + ", ".join(task_unexpected))

    # Syntax check: on total worktree changes (preserves existing behavior).
    for change in total_changes:
        if change.path.endswith(".py") and change.content:
            try:
                ast.parse(change.content, filename=change.path)
            except (SyntaxError, ValueError) as exc:
                blockers.append(f"Python syntax error in {change.path}: {exc}")

    evidence_status = classify_evidence(evidence)
    if evidence_status == "not_run":
        warnings.append("validation was not reported")
    elif evidence_status == "reported_passed":
        warnings.append("validation was reported but not independently observed")
    if uncertainty and uncertainty.strip():
        warnings.append("remaining uncertainty: " + uncertainty.strip())

    return {"passed": not blockers, "blockers": blockers, "warnings": warnings,
            "changed_files": total_changed_files, "diff_digest": digest_changes(total_changes),
            "task_changed_files": task_changed_files,
            "task_diff_digest": digest_changes(task_changes),
            "preexisting_dirty_files": preexisting_dirty_files,
            "total_worktree_changed_files": total_changed_files,
            "baseline_tree_id": baseline_tree_id,
            "current_tree_id": current_tree_id,
            "unexplained_changed_files": [],
            "mutation_ledger_summary": None,
            "evidence_status": evidence_status, "ready_to_finish": not blockers,
            "reviewed_at": _timestamp(clock()),
            "semantic_correctness_observed": False,
            "agent_step_intent": agent_step_intent,
            "target_behavior_claim": target_behavior_claim,
            "owner_boundary_claim": owner_boundary_claim,
            "proof_plan": proof_plan}


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")
