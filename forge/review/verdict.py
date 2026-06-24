from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
import ast
from typing import Any, Callable

from .baseline import capture_tree, diff_trees
from .diff import RepositoryInspectionError, capture_changes, digest_changes, safe_path
from .evidence import classify_evidence


def _tree_exists(repo: Path, tree_id: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", tree_id],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False,
    )
    return result.returncode == 0 and result.stdout.strip() == b"tree"


def _path_covered_by_expansion(file_path: str, expansion_path: str) -> bool:
    fp = file_path.rstrip("/")
    ep = expansion_path.rstrip("/")
    if fp == ep:
        return True
    if fp.startswith(ep + "/"):
        return True
    return False


def _normalize_expansions(repo: Path, raw: list[dict[str, Any]]) -> tuple[
    list[dict[str, Any]],
    list[str],
    list[str],
]:
    normalized: list[dict[str, Any]] = []
    hard_issues: list[str] = []
    soft_issues: list[str] = []
    seen_paths: set[str] = set()

    for i, exp in enumerate(raw):
        path_raw = (exp.get("path") or "").strip()
        reason = (exp.get("reason") or "").strip()

        if not path_raw:
            hard_issues.append(f"expansion[{i}]: path is empty")
            continue

        try:
            validated = safe_path(repo, path_raw)
            path_norm = validated.relative_to(repo).as_posix()
        except Exception as exc:
            hard_issues.append(f"expansion[{i}] path={path_raw!r}: invalid ({exc})")
            continue

        if path_norm in seen_paths:
            soft_issues.append(f"expansion[{i}] path={path_norm}: duplicate (already declared)")
            continue

        seen_paths.add(path_norm)
        normalized.append({
            "path": path_norm,
            "reason": reason,
            "relationship_to_task": exp.get("relationship_to_task", "").strip() or None,
            "risk": exp.get("risk", "").strip() or None,
            "validation": exp.get("validation", "").strip() or None,
        })

    return normalized, hard_issues, soft_issues


def _fail(repo_inspect_error: str, evidence: list[dict[str, Any]] | None,
          clock: Callable[[], float],
          agent_step_intent: str | None,
          target_behavior_claim: str | None,
          owner_boundary_claim: str | None,
          proof_plan: str | None,
          scope_expansions: list[dict[str, Any]] | None = None,
          session_digest: dict | None = None) -> dict[str, Any]:
    return {"passed": False, "blockers": [f"repository cannot be inspected: {repo_inspect_error}"],
            "warnings": [], "changed_files": [], "diff_digest": None,
            "task_changed_files": [], "task_diff_digest": None,
            "preexisting_dirty_files": [], "total_worktree_changed_files": [],
            "baseline_tree_id": None, "current_tree_id": None,
            "unexplained_changed_files": [], "mutation_ledger_summary": None,
            "evidence_status": classify_evidence(evidence, session_digest=session_digest), "ready_to_finish": False,
            "reviewed_at": _timestamp(clock()),
            "semantic_correctness_observed": False,
            "agent_step_intent": agent_step_intent,
            "target_behavior_claim": target_behavior_claim,
            "owner_boundary_claim": owner_boundary_claim,
            "proof_plan": proof_plan,
            "scope_expansions_declared": scope_expansions or [],
            "out_of_scope_undeclared_files": []}


def review_repository(repo: Path, expected_files: list[str], scope_mode: str,
                      evidence: list[dict[str, Any]] | None, uncertainty: str | None,
                      clock: Callable[[], float], *,
                      agent_step_intent: str | None = None,
                      target_behavior_claim: str | None = None,
                      owner_boundary_claim: str | None = None,
                      proof_plan: str | None = None,
                      baseline_tree_id: str | None = None,
                      scope_expansions: list[dict[str, Any]] | None = None,
                      session_digest: dict | None = None) -> dict[str, Any]:
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
                         owner_boundary_claim, proof_plan,
                         scope_expansions=scope_expansions,
                         session_digest=session_digest)

    # ---------- baseline-aware deltas ----------------------------------------
    if baseline_available:
        repo_path = repo
        try:
            assert baseline_tree_id is not None
            if not _tree_exists(repo_path, baseline_tree_id):
                warnings.append("baseline tree object no longer exists; "
                                "task delta cannot be isolated from pre-existing changes")
                baseline_available = False
        except (subprocess.CalledProcessError, OSError):
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

    # Narrow to session-attributed files when transcript evidence is available.
    session_edited_raw = (session_digest or {}).get("edited_files") or []
    if session_edited_raw and task_changed_files:
        session_edited: list[str] = []
        for raw_path in session_edited_raw:
            p = Path(raw_path)
            if p.is_absolute():
                try:
                    session_edited.append(p.relative_to(repo).as_posix())
                except ValueError:
                    pass
            else:
                session_edited.append(raw_path)
        if session_edited:
            edited_set = frozenset(session_edited)
            unattributed = sorted(set(task_changed_files) - edited_set)
            if unattributed:
                warnings.append(
                    "files changed outside this session (concurrent or side-effect): "
                    + ", ".join(unattributed))
            task_changed_files = sorted(edited_set & set(task_changed_files))
            narrowed_paths = set(task_changed_files)
            task_changes = [c for c in task_changes if c.path in narrowed_paths]

    # No-change blocker: uses task delta.
    if not task_changes:
        blockers.append("no changes found for implementation task")

    # Scope check with scope-expansion support (scope_mode-gated).
    task_unexpected = sorted(set(task_changed_files) - set(expected_files)) if expected_files else []
    normalized_expansions: list[dict[str, Any]] = []
    out_of_scope_undeclared: list[str] = []

    # Normalize expansions when provided, even if no unexpected files exist
    # (so that warnings like duplicate/unused/ignored can fire).
    if scope_expansions is not None:
        normalized_expansions, hard_issues, soft_issues = _normalize_expansions(repo, scope_expansions)

        for issue in soft_issues:
            warnings.append(f"scope_expansions note: {issue}")
        for issue in hard_issues:
            if scope_mode == "strict":
                blockers.append(f"invalid scope_expansions: {issue}")
            else:
                warnings.append(f"scope_expansions note: {issue}")

    if task_unexpected:
        if scope_expansions is not None:
            for path in task_unexpected:
                covered = any(
                    _path_covered_by_expansion(path, exp["path"])
                    for exp in normalized_expansions
                )
                if not covered:
                    out_of_scope_undeclared.append(path)

            for i, exp in enumerate(normalized_expansions):
                if not exp["reason"]:
                    msg = f"expansion[{i}] path={exp['path']}: reason is required"
                    if scope_mode == "strict":
                        blockers.append(msg)
                    else:
                        warnings.append(msg)

            if out_of_scope_undeclared:
                msg = ("out-of-scope changed files not covered by any scope-expansion: "
                       + ", ".join(out_of_scope_undeclared))
                if scope_mode == "strict":
                    blockers.append(msg)
                    blockers.append("resubmit review_changes with scope_expansions "
                                    "declaring each remaining out-of-scope file or directory")
                else:
                    warnings.append(msg)
        else:
            if scope_mode == "strict":
                blockers.append(
                    "out-of-scope changed files without scope-expansion declaration: "
                    + ", ".join(task_unexpected))
                blockers.append(
                    "resubmit review_changes with scope_expansions declaring each "
                    "out-of-scope file or directory with a reason")
            else:
                warnings.append("changed files outside expected scope: "
                                + ", ".join(task_unexpected))

    if normalized_expansions and expected_files:
        covered_any: set[str] = set()
        for path in task_unexpected:
            for exp in normalized_expansions:
                if _path_covered_by_expansion(path, exp["path"]):
                    covered_any.add(exp["path"])
        for exp in normalized_expansions:
            if exp["path"] not in covered_any:
                warnings.append(
                    f"scope expansion '{exp['path']}' did not cover any out-of-scope file")

    if expected_files == [] and scope_expansions is not None:
        warnings.append("scope_expansions ignored because no expected_files were declared")

    if normalized_expansions and not out_of_scope_undeclared and expected_files:
        expanded = sorted(set(e["path"] for e in normalized_expansions))
        warnings.append("scope expanded to: " + ", ".join(expanded))

    # Syntax check: on total worktree changes (preserves existing behavior).
    for change in total_changes:
        if change.path.endswith(".py") and change.content:
            try:
                ast.parse(change.content, filename=change.path)
            except (SyntaxError, ValueError) as exc:
                blockers.append(f"Python syntax error in {change.path}: {exc}")

    evidence_status = classify_evidence(evidence, session_digest=session_digest)
    if evidence_status == "not_run":
        warnings.append("validation was not reported")
    elif evidence_status == "reported_passed":
        warnings.append("validation was reported but not independently observed")
    elif evidence_status == "observed_failed":
        warnings.append("transcript observed failing tests but review passed")
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
            "proof_plan": proof_plan,
            "scope_expansions_declared": normalized_expansions,
            "out_of_scope_undeclared_files": out_of_scope_undeclared}


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")
