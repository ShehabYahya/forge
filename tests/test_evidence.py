from forge.review.evidence import classify_evidence, _classify_test_output


def test_classify_cargo_test_passing():
    output = "test result: ok. 3 passed; 0 failed; 0 ignored"
    assert _classify_test_output(output) == "passed"


def test_classify_cargo_test_with_real_failures():
    output = "2 failed, 3 passed"
    assert _classify_test_output(output) == "failed"


def test_classify_zero_failed_no_passes_is_unclear():
    output = "0 failed"
    assert _classify_test_output(output) == "unclear"


def test_classify_running_zero_tests():
    output = "running 0 tests\n0 failed"
    assert _classify_test_output(output) == "unclear"


def test_classify_bare_failed_is_failed():
    output = "FAILED"
    assert _classify_test_output(output) == "failed"


def test_classify_node_test_passing():
    output = "# pass 17\n# fail 0"
    assert _classify_test_output(output) == "passed"


def test_classify_unittest_ok():
    output = "OK\n"
    assert _classify_test_output(output) == "passed"


def test_classify_pytest_passing():
    output = "3 passed in 0.12s"
    assert _classify_test_output(output) == "passed"


def test_classify_pytest_failing():
    output = "2 failed, 3 passed"
    assert _classify_test_output(output) == "failed"


def test_classify_exit_status_1():
    output = "exit status 1"
    assert _classify_test_output(output) == "failed"


def test_classify_exit_status_2():
    output = "exit status 2"
    assert _classify_test_output(output) == "failed"


def test_classify_traceback():
    output = "Traceback (most recent call last):"
    assert _classify_test_output(output) == "failed"


def test_classify_failing_single():
    output = "test_failing ... FAILED"
    assert _classify_test_output(output) == "failed"


def test_classify_rake_test_passing():
    output = "rake test: 5 tests, 5 passed, 0 failures"
    assert _classify_test_output(output) == "passed"


def test_classify_mvn_test_failing():
    output = "Tests run: 5, Failures: 1, Errors: 0"
    assert _classify_test_output(output) == "failed"


def test_classify_dotnet_test_passing():
    output = "Passed!  - Failed:     0, Passed:     3"
    assert _classify_test_output(output) == "passed"


def test_classify_observed_passed():
    digest = {"test_runs": [{"command": "pytest", "output": "3 passed"}]}
    assert classify_evidence(None, session_digest=digest) == "observed_passed"


def test_classify_observed_failed():
    digest = {"test_runs": [{"command": "pytest", "output": "2 failed, 1 passed"}]}
    assert classify_evidence(None, session_digest=digest) == "observed_failed"


def test_classify_observed_mixed():
    digest = {"test_runs": [
        {"command": "pytest", "output": "3 passed"},
        {"command": "cargo test", "output": "0 failed"},
    ]}
    assert classify_evidence(None, session_digest=digest) == "observed_passed"


def test_classify_observed_unclear():
    digest = {"test_runs": [{"command": "pytest", "output": "no output"}]}
    assert classify_evidence(None, session_digest=digest) == "observed_unclear"


def test_classify_no_test_runs_falls_to_reported():
    assert classify_evidence([{"status": "passed"}]) == "reported_passed"


def test_classify_no_test_runs_no_reported():
    assert classify_evidence(None) == "not_run"


def test_classify_no_test_runs_reported_failed():
    assert classify_evidence([{"status": "failed"}]) == "reported_failed"


def test_classify_error_zero_not_failed():
    output = "Error: 0"
    assert _classify_test_output(output) != "failed"


def test_classify_errors_zero_not_failed():
    output = "Errors: 0"
    assert _classify_test_output(output) != "failed"


def test_classify_bare_passed_is_passed():
    output = "PASSED\n"
    assert _classify_test_output(output) == "passed"


def test_classify_bare_ok_is_passed():
    output = "OK\n"
    assert _classify_test_output(output) == "passed"


# -------------------------------------------------- exit-code-aware classification


def test_exit_code_1_with_passing_text_is_failed():
    digest = {"test_runs": [{"command": "pytest", "output": "3 passed", "exit_code": 1}]}
    assert classify_evidence(None, session_digest=digest) == "observed_failed"


def test_exit_code_0_with_passing_text_is_passed():
    digest = {"test_runs": [{"command": "pytest", "output": "3 passed", "exit_code": 0}]}
    assert classify_evidence(None, session_digest=digest) == "observed_passed"


def test_exit_code_nonzero_with_any_run_is_failed():
    digest = {"test_runs": [
        {"command": "pytest", "output": "3 passed", "exit_code": 0},
        {"command": "cargo test", "output": "ok", "exit_code": 1},
    ]}
    assert classify_evidence(None, session_digest=digest) == "observed_failed"


def test_exit_code_0_with_unclear_output_is_unclear():
    digest = {"test_runs": [{"command": "pytest", "output": "no output", "exit_code": 0}]}
    assert classify_evidence(None, session_digest=digest) == "observed_unclear"


def test_exit_code_0_with_failing_text_is_not_failed():
    digest = {"test_runs": [{"command": "pytest", "output": "2 failed, 1 passed", "exit_code": 0}]}
    assert classify_evidence(None, session_digest=digest) == "observed_unclear"


def test_exit_code_missing_falls_back_to_heuristic():
    digest = {"test_runs": [{"command": "pytest", "output": "3 passed"}]}
    assert classify_evidence(None, session_digest=digest) == "observed_passed"


def test_exit_code_none_falls_back_to_heuristic():
    digest = {"test_runs": [{"command": "pytest", "output": "2 failed", "exit_code": None}]}
    assert classify_evidence(None, session_digest=digest) == "observed_failed"


def test_legacy_no_exit_code_observed_passed():
    digest = {"test_runs": [{"command": "pytest", "output": "3 passed"}]}
    assert classify_evidence(None, session_digest=digest) == "observed_passed"


def test_legacy_no_exit_code_observed_failed():
    digest = {"test_runs": [{"command": "pytest", "output": "2 failed, 1 passed"}]}
    assert classify_evidence(None, session_digest=digest) == "observed_failed"
