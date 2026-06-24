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
                "unexplained_changed_files", "mutation_ledger_summary",
                "scope_expansions_declared", "out_of_scope_undeclared_files"):
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


# ---------------------------------------------------- scope expansion tests


def test_all_in_scope_proceeds(repo):
    (repo / "expected.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0)
    assert result["passed"]
    assert not any("scope" in b.lower() for b in result["blockers"])


def test_out_of_scope_no_expansion_strict_blocks(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0)
    assert not result["passed"]
    assert any("without scope-expansion declaration" in b for b in result["blockers"])
    assert any("scope_expansions" in b for b in result["blockers"])


def test_out_of_scope_no_expansion_warning_proceeds(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "warning", None, None, lambda: 0)
    assert result["passed"]
    assert any("outside expected scope" in w.lower() for w in result["warnings"])


def test_out_of_scope_valid_expansion_strict_proceeds(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "other.py", "reason": "required refactor"}])
    assert result["passed"]
    assert result["scope_expansions_declared"] == [
        {"path": "other.py", "reason": "required refactor",
         "relationship_to_task": None, "risk": None, "validation": None}]


def test_out_of_scope_partial_expansion_strict_blocks(repo):
    (repo / "src").mkdir()
    (repo / "src/a.py").write_text("x=1\n")
    (repo / "src/b.py").write_text("x=2\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "src/a.py", "reason": "needed a"}])
    assert not result["passed"]
    assert any("not covered by any scope-expansion" in b for b in result["blockers"])
    assert "src/b.py" in str(result["blockers"])
    assert "src/b.py" in result["out_of_scope_undeclared_files"]
    assert "resubmit" in " ".join(result["blockers"])


def test_out_of_scope_partial_expansion_warning_proceeds(repo):
    (repo / "src").mkdir()
    (repo / "src/a.py").write_text("x=1\n")
    (repo / "src/b.py").write_text("x=2\n")
    result = review_repository(repo, ["expected.py"], "warning", None, None, lambda: 0,
                               scope_expansions=[{"path": "src/a.py", "reason": "needed a"}])
    assert result["passed"]
    assert any("not covered by any scope-expansion" in w for w in result["warnings"])
    assert "src/b.py" in result["out_of_scope_undeclared_files"]


def test_expansion_empty_reason_strict_blocks(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "other.py", "reason": ""}])
    assert not result["passed"]
    assert any("reason is required" in b for b in result["blockers"])


def test_expansion_empty_reason_warning_proceeds(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "warning", None, None, lambda: 0,
                               scope_expansions=[{"path": "other.py", "reason": ""}])
    assert result["passed"]
    assert any("reason is required" in w for w in result["warnings"])


def test_directory_expansion_covers_nested(repo):
    (repo / "src/sub").mkdir(parents=True)
    (repo / "src/sub/nested.py").write_text("x=1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "src", "reason": "whole src needed"}])
    assert result["passed"]
    assert "nested.py" not in str(result["blockers"])


def test_unrelated_expansion_does_not_cover(repo):
    (repo / "src").mkdir()
    (repo / "src/foo.py").write_text("x=1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "other", "reason": "unrelated"}])
    assert not result["passed"]
    assert any("not covered by any scope-expansion" in b for b in result["blockers"])
    assert "src/foo.py" in result["out_of_scope_undeclared_files"]


def test_duplicate_expansion_warned(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[
                                   {"path": "other.py", "reason": "first"},
                                   {"path": "other.py", "reason": "duplicate"},
                               ])
    assert result["passed"]
    assert any("duplicate" in w.lower() for w in result["warnings"])


def test_empty_expansion_path_validated(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "", "reason": "whoops"}])
    assert not result["passed"]
    assert any("path is empty" in b for b in result["blockers"])


def test_empty_expansion_path_warning_mode(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "warning", None, None, lambda: 0,
                               scope_expansions=[{"path": "", "reason": "whoops"}])
    assert result["passed"]
    assert any("path is empty" in w for w in result["warnings"])


def test_expansion_path_escape_rejected(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "../escape", "reason": "bad"}])
    assert not result["passed"]
    assert any("invalid" in b.lower() for b in result["blockers"])


def test_unused_expansion_warned(repo):
    (repo / "legit.py").write_text("x = 1\n")
    result = review_repository(repo, ["legit.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "untouched", "reason": "not needed"}])
    assert result["passed"]
    assert any("did not cover any out-of-scope" in w for w in result["warnings"])


def test_expansions_ignored_when_no_expected_files(repo):
    (repo / "x.txt").write_text("x\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "x.txt", "reason": "present"}])
    assert result["passed"]
    assert any("ignored because no expected_files" in w for w in result["warnings"])


def test_scope_expansions_declared_in_verdict(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "other.py", "reason": "needed",
                                                  "risk": "low", "validation": "tested"}])
    assert "scope_expansions_declared" in result
    assert "out_of_scope_undeclared_files" in result
    assert result["out_of_scope_undeclared_files"] == []
    assert len(result["scope_expansions_declared"]) == 1
    assert result["scope_expansions_declared"][0]["risk"] == "low"
    assert result["scope_expansions_declared"][0]["validation"] == "tested"


def test_fail_includes_scope_fields(tmp_path):
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    result = review_repository(
        empty, [], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "x", "reason": "r"}])
    assert "scope_expansions_declared" in result
    assert "out_of_scope_undeclared_files" in result
    assert result["out_of_scope_undeclared_files"] == []
    assert result["scope_expansions_declared"] == [{"path": "x", "reason": "r"}]


def test_backward_compat_no_expansions_no_out_of_scope(repo):
    (repo / "x.txt").write_text("x\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0)
    assert result["passed"]
    assert result["scope_expansions_declared"] == []
    assert result["out_of_scope_undeclared_files"] == []


def test_scope_expanded_warning_when_accepted(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(repo, ["expected.py"], "strict", None, None, lambda: 0,
                               scope_expansions=[{"path": "other.py", "reason": "required"}])
    assert result["passed"]
    assert any("scope expanded to" in w for w in result["warnings"])
