from forge.review.baseline import capture_tree
from forge.review.verdict import review_repository


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


def test_narrative_fields_round_trip_into_verdict(repo):
    (repo / "x.txt").write_text("x")
    result = review_repository(
        repo, [], "strict", [{"status": "passed"}], None, lambda: 0,
        agent_step_intent="step intent",
        target_behavior_claim="target behavior",
        owner_boundary_claim="owner boundary",
        proof_plan="proof plan",
    )
    assert result["agent_step_intent"] == "step intent"
    assert result["target_behavior_claim"] == "target behavior"
    assert result["owner_boundary_claim"] == "owner boundary"
    assert result["proof_plan"] == "proof plan"
    assert "observed_passed" not in str(result)


def test_narrative_fields_default_to_none_when_omitted(repo):
    (repo / "x.txt").write_text("x")
    result = review_repository(repo, [], "strict", None, None, lambda: 0)
    assert result["agent_step_intent"] is None
    assert result["target_behavior_claim"] is None
    assert result["owner_boundary_claim"] is None
    assert result["proof_plan"] is None
    assert "observed_passed" not in str(result)


def test_narrative_fields_present_even_on_inspection_error(tmp_path):
    # A path that is not a git repository triggers the inspection-error branch,
    # which must still carry the four narrative fields.
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    result = review_repository(
        empty, [], "strict", None, None, lambda: 0,
        agent_step_intent="intent", target_behavior_claim="claim",
        owner_boundary_claim="boundary", proof_plan="plan",
    )
    assert not result["passed"]
    assert result["agent_step_intent"] == "intent"
    assert result["target_behavior_claim"] == "claim"
    assert result["owner_boundary_claim"] == "boundary"
    assert result["proof_plan"] == "plan"
    assert "observed_passed" not in str(result)


# ---------------------------------------------------- baseline-aware review


def test_task_changed_files_excludes_preexisting_dirt(repo):
    (repo / "dirty.txt").write_text("pre-existing\n")
    baseline = capture_tree(repo)
    (repo / "task.txt").write_text("agent change\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0,
                               baseline_tree_id=baseline)
    assert "task.txt" in result["task_changed_files"]
    assert "dirty.txt" in result["preexisting_dirty_files"]
    assert "dirty.txt" not in result["task_changed_files"]


def test_no_changes_blocker_uses_task_delta(repo):
    (repo / "dirty.txt").write_text("pre-existing\n")
    baseline = capture_tree(repo)
    result = review_repository(repo, [], "strict", None, None, lambda: 0,
                               baseline_tree_id=baseline)
    assert not result["passed"]
    assert any("no changes" in b.lower() for b in result["blockers"])
    assert "dirty.txt" in result["preexisting_dirty_files"]


def test_scope_check_uses_task_changed_files(repo):
    (repo / "dirty_outside.txt").write_text("pre-existing\n")
    baseline = capture_tree(repo)
    (repo / "expected.py").write_text("x=1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None,
                               lambda: 0, baseline_tree_id=baseline)
    assert result["passed"]


def test_old_keys_preserved(repo):
    (repo / "x.txt").write_text("x\n")
    baseline = capture_tree(repo)
    (repo / "y.txt").write_text("y\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0,
                               baseline_tree_id=baseline)
    assert "x.txt" in result["changed_files"]
    assert "y.txt" in result["changed_files"]
    assert result["diff_digest"] is not None


def test_baseline_unavailable_fallback(repo):
    (repo / "x.txt").write_text("x\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0,
                               baseline_tree_id=None)
    assert result["changed_files"] == result["task_changed_files"]
    assert result["diff_digest"] == result["task_diff_digest"]


def test_new_keys_all_present(repo):
    (repo / "x.txt").write_text("x\n")
    baseline = capture_tree(repo)
    (repo / "y.txt").write_text("y\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0,
                               baseline_tree_id=baseline)
    for key in ("task_changed_files", "task_diff_digest",
                "preexisting_dirty_files", "total_worktree_changed_files",
                "baseline_tree_id", "current_tree_id",
                "unexplained_changed_files", "mutation_ledger_summary"):
        assert key in result


def test_unexplained_and_ledger_placeholders(repo):
    (repo / "x.txt").write_text("x\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0,
                               baseline_tree_id=capture_tree(repo))
    assert result["unexplained_changed_files"] == []
    assert result["mutation_ledger_summary"] is None


def test_baseline_tree_missing_gc_fallback(repo):
    """A baseline tree SHA that does not exist triggers warning+fallback."""
    fake_sha = "0" * 40
    (repo / "x.txt").write_text("x\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0,
                               baseline_tree_id=fake_sha)
    assert any("baseline tree" in w.lower() for w in result["warnings"])

