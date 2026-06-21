from forge.review.verdict import parse_anvil_verdict, review_repository


def test_strict_and_warning_scope_differ(repo):
    (repo / "other.py").write_text("x = 1\n")
    strict = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0)
    warning = review_repository(repo, ["expected.py"], "warning", None, None, lambda: 0)
    assert not strict["passed"] and warning["passed"]
    assert warning["semantic_correctness_observed"] is False


def test_python_syntax_error_blocks(repo):
    (repo / "bad.py").write_text("def broken(:\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0)
    assert not result["passed"] and any("syntax" in item.lower() for item in result["blockers"])


def test_reported_evidence_is_never_observed(repo):
    (repo / "x.txt").write_text("x")
    result = review_repository(repo, [], "strict", [{"status": "passed"}], "uncertain", lambda: 0)
    assert result["evidence_status"] == "reported_passed"
    assert "observed_passed" not in str(result)


def test_anvil_verdict_must_be_valid_first_line():
    assert parse_anvil_verdict("APPROVE\nnotes") == "APPROVE"
    assert parse_anvil_verdict("notes\nAPPROVE") == "REVIEW_FAILED"
    assert parse_anvil_verdict("UNKNOWN") == "REVIEW_FAILED"

