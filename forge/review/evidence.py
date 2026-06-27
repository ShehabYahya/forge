from __future__ import annotations

import re
from typing import Any


def classify_evidence(reported: list[dict[str, Any]] | None,
                      session_digest: dict | None = None) -> str:
    test_runs = (session_digest or {}).get("test_runs") or []
    if test_runs:
        passed = 0
        failed = 0
        for run in test_runs:
            if not isinstance(run, dict):
                continue
            result = _classify_test_output(str(run.get("output", "")))
            if result == "passed":
                passed += 1
            elif result == "failed":
                failed += 1
        if failed == 0 and passed > 0:
            return "observed_passed"
        if failed > 0:
            return "observed_failed"
        return "observed_unclear"

    # No test_runs → fall through to agent-reported evidence
    if not reported:
        return "not_run"
    statuses = {str(item.get("status", "")).lower() for item in reported}
    if statuses & {"failed", "fail", "error"}:
        return "reported_failed"
    if statuses & {"passed", "pass", "ok", "success"}:
        return "reported_passed"
    return "unknown"


def _classify_test_output(output: str) -> str:
    lower = output.lower()
    has_pass = any(i in lower for i in [
        " passed", " ok ", "all tests passed", "test result: ok",
        "passing", "success", " tests passed", "ok\n", "# pass ", "# pass:",
        "\npassed", "passed\n",
    ])
    has_fail = any(i in lower for i in [
        "failures=", "assertionerror",
        "test result: fail", "exit status 1", "exit status 2",
        "traceback", "tests failed", "failing",
    ])
    if not has_fail:
        if re.search(r'(?<!\d)\b[1-9]\d*\s*(?:failed|failures?|errors?)\b', lower):
            has_fail = True
        elif re.search(r'\b(?:failed|failures?|errors?|error)\s*:\s*[1-9]\d*\b', lower):
            has_fail = True
        elif re.search(r'\bexit status [1-9]\d*\b', lower):
            has_fail = True
        elif re.search(r'\berror\s*:\s*[1-9]\d*\b', lower):
            has_fail = True
        elif re.search(r'\b(?:failed|fail)\b', lower) and not (
                re.search(r'\b0\s+(?:failed|fail)\b', lower) or
                re.search(r'\b(?:failed|fail)\s+0\b', lower) or
                re.search(r'\b(?:failed|failures?|errors?)\s*:\s*0\b', lower)):
            has_fail = True

    if has_pass and not has_fail:
        return "passed"
    if has_fail:
        return "failed"
    return "unclear"
