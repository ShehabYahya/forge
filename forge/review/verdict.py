from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import ast
from typing import Any, Callable

from .diff import RepositoryInspectionError, capture_changes, digest_changes
from .evidence import classify_evidence

ANVIL_VERDICTS = frozenset({"APPROVE", "APPROVE_WITH_NOTES", "REQUEST_CHANGES", "REJECT", "REVIEW_FAILED"})


def parse_anvil_verdict(value: str) -> str:
    first_line = value.splitlines()[0].strip() if value else ""
    return first_line if first_line in ANVIL_VERDICTS else "REVIEW_FAILED"


def review_repository(repo: Path, expected_files: list[str], scope_mode: str,
                      evidence: list[dict[str, Any]] | None, uncertainty: str | None,
                      clock: Callable[[], float]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    try:
        changes = capture_changes(repo)
    except RepositoryInspectionError as exc:
        return {"passed": False, "blockers": [f"repository cannot be inspected: {exc}"],
                "warnings": [], "changed_files": [], "diff_digest": None,
                "evidence_status": classify_evidence(evidence), "ready_to_finish": False,
                "reviewed_at": _timestamp(clock())}
    if not changes:
        blockers.append("no changes found for implementation task")
    changed_files = [item.path for item in changes]
    unexpected = sorted(set(changed_files) - set(expected_files)) if expected_files else []
    if unexpected and scope_mode == "strict":
        blockers.append("changed files outside strict expected scope: " + ", ".join(unexpected))
    elif unexpected:
        warnings.append("changed files outside expected scope: " + ", ".join(unexpected))
    for change in changes:
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
            "changed_files": changed_files, "diff_digest": digest_changes(changes),
            "evidence_status": evidence_status, "ready_to_finish": not blockers,
            "reviewed_at": _timestamp(clock()),
            "semantic_correctness_observed": False}


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")
