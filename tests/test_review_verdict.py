from forge.review.verdict import review_repository


def session_digest(*paths: str, digest: str = "digest-1", test_runs=None):
    return {
        "edited_files": list(paths),
        "edited_files_digest": digest,
        "test_runs": test_runs or [],
    }


def test_strict_and_warning_scope_differ(repo):
    (repo / "other.py").write_text("x = 1\n")
    strict = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        session_digest=session_digest("other.py"),
    )
    warning = review_repository(
        repo, ["expected.py"], "warning", None, None, lambda: 0,
        session_digest=session_digest("other.py"),
    )
    assert not strict["passed"] and warning["passed"]
    assert warning["semantic_correctness_observed"] is False


def test_python_syntax_error_blocks(repo):
    (repo / "bad.py").write_text("def broken(:\n")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=session_digest("bad.py"),
    )
    assert not result["passed"] and any("syntax" in item.lower() for item in result["blockers"])


def test_reported_evidence_is_never_observed(repo):
    (repo / "x.txt").write_text("x")
    result = review_repository(
        repo, [], "strict", [{"status": "passed"}], "uncertain", lambda: 0,
        session_digest=session_digest("x.txt"),
    )
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
        session_digest=session_digest("x.txt"),
    )
    assert result["agent_step_intent"] == "step intent"
    assert result["target_behavior_claim"] == "target behavior"
    assert result["owner_boundary_claim"] == "owner boundary"
    assert result["proof_plan"] == "proof plan"
    assert "observed_passed" not in str(result)


def test_narrative_fields_default_to_none_when_omitted(repo):
    (repo / "x.txt").write_text("x")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=session_digest("x.txt"),
    )
    assert result["agent_step_intent"] is None
    assert result["target_behavior_claim"] is None
    assert result["owner_boundary_claim"] is None
    assert result["proof_plan"] is None
    assert "observed_passed" not in str(result)


def test_narrative_fields_present_even_on_inspection_error(tmp_path):
    empty = tmp_path / "not-a-repo"
    empty.mkdir()
    result = review_repository(
        empty, [], "strict", None, None, lambda: 0,
        agent_step_intent="intent", target_behavior_claim="claim",
        owner_boundary_claim="boundary", proof_plan="plan",
        session_digest=session_digest("x.txt"),
    )
    assert not result["passed"]
    assert result["agent_step_intent"] == "intent"
    assert result["target_behavior_claim"] == "claim"
    assert result["owner_boundary_claim"] == "boundary"
    assert result["proof_plan"] == "plan"
    assert "observed_passed" not in str(result)


def test_missing_session_digest_is_capability_limited(repo):
    (repo / "x.txt").write_text("x\n")
    result = review_repository(repo, [], "strict", None, None, lambda: 0)
    assert not result["passed"]
    assert result["capability_limited"] is True
    assert any("session-backed review" in blocker for blocker in result["blockers"])


def test_review_uses_session_digest_not_preexisting_dirt(repo):
    (repo / "dirty.txt").write_text("pre-existing\n")
    (repo / "task.txt").write_text("agent change\n")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=session_digest("task.txt"),
    )
    assert result["task_changed_files"] == ["task.txt"]
    assert result["preexisting_dirty_files"] == []


def test_no_changes_blocker_uses_session_digest(repo):
    (repo / "dirty.txt").write_text("pre-existing\n")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=session_digest(digest="clean-1"),
    )
    assert not result["passed"]
    assert any("no changes" in b.lower() for b in result["blockers"])


def test_scope_check_uses_session_changed_files(repo):
    (repo / "dirty_outside.txt").write_text("pre-existing\n")
    (repo / "expected.py").write_text("x=1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        session_digest=session_digest("expected.py"),
    )
    assert result["passed"]


def test_old_keys_preserved(repo):
    (repo / "x.txt").write_text("x\n")
    (repo / "y.txt").write_text("y\n")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=session_digest("x.txt", "y.txt", digest="digest-xy"),
    )
    assert result["changed_files"] == ["x.txt", "y.txt"]
    assert result["diff_digest"] == "digest-xy"


def test_compatibility_fields_are_empty_or_null(repo):
    (repo / "x.txt").write_text("x\n")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=session_digest("x.txt"),
    )
    assert result["changed_files"] == result["task_changed_files"]
    assert result["diff_digest"] == result["task_diff_digest"]
    assert result["preexisting_dirty_files"] == []
    assert result["baseline_tree_id"] is None
    assert result["current_tree_id"] is None


def test_new_keys_all_present(repo):
    (repo / "x.txt").write_text("x\n")
    (repo / "y.txt").write_text("y\n")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=session_digest("x.txt", "y.txt"),
    )
    for key in (
        "task_changed_files", "task_diff_digest",
        "preexisting_dirty_files", "total_worktree_changed_files",
        "baseline_tree_id", "current_tree_id",
        "unexplained_changed_files", "mutation_ledger_summary",
        "scope_expansions_declared", "out_of_scope_undeclared_files",
        "capability_limited",
    ):
        assert key in result


def test_unexplained_and_ledger_placeholders(repo):
    (repo / "x.txt").write_text("x\n")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=session_digest("x.txt"),
    )
    assert result["unexplained_changed_files"] == []
    assert result["mutation_ledger_summary"] is None


def test_all_in_scope_proceeds(repo):
    (repo / "expected.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        session_digest=session_digest("expected.py"),
    )
    assert result["passed"]
    assert not any("scope" in b.lower() for b in result["blockers"])


def test_out_of_scope_no_expansion_strict_blocks(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        session_digest=session_digest("other.py"),
    )
    assert not result["passed"]
    assert any("without scope-expansion declaration" in b for b in result["blockers"])
    assert any("scope_expansions" in b for b in result["blockers"])


def test_out_of_scope_no_expansion_warning_proceeds(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "warning", None, None, lambda: 0,
        session_digest=session_digest("other.py"),
    )
    assert result["passed"]
    assert any("outside expected scope" in w.lower() for w in result["warnings"])


def test_out_of_scope_valid_expansion_strict_proceeds(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "other.py", "reason": "required refactor"}],
        session_digest=session_digest("other.py"),
    )
    assert result["passed"]
    assert result["scope_expansions_declared"] == [
        {"path": "other.py", "reason": "required refactor",
         "relationship_to_task": None, "risk": None, "validation": None}]


def test_out_of_scope_partial_expansion_strict_blocks(repo):
    (repo / "src").mkdir()
    (repo / "src/a.py").write_text("x=1\n")
    (repo / "src/b.py").write_text("x=2\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "src/a.py", "reason": "needed a"}],
        session_digest=session_digest("src/a.py", "src/b.py"),
    )
    assert not result["passed"]
    assert any("not covered by any scope-expansion" in b for b in result["blockers"])
    assert "src/b.py" in str(result["blockers"])
    assert "src/b.py" in result["out_of_scope_undeclared_files"]
    assert "resubmit" in " ".join(result["blockers"])


def test_out_of_scope_partial_expansion_warning_proceeds(repo):
    (repo / "src").mkdir()
    (repo / "src/a.py").write_text("x=1\n")
    (repo / "src/b.py").write_text("x=2\n")
    result = review_repository(
        repo, ["expected.py"], "warning", None, None, lambda: 0,
        scope_expansions=[{"path": "src/a.py", "reason": "needed a"}],
        session_digest=session_digest("src/a.py", "src/b.py"),
    )
    assert result["passed"]
    assert any("not covered by any scope-expansion" in w for w in result["warnings"])
    assert "src/b.py" in result["out_of_scope_undeclared_files"]


def test_expansion_empty_reason_strict_blocks(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "other.py", "reason": ""}],
        session_digest=session_digest("other.py"),
    )
    assert not result["passed"]
    assert any("reason is required" in b for b in result["blockers"])


def test_expansion_empty_reason_warning_proceeds(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "warning", None, None, lambda: 0,
        scope_expansions=[{"path": "other.py", "reason": ""}],
        session_digest=session_digest("other.py"),
    )
    assert result["passed"]
    assert any("reason is required" in w for w in result["warnings"])


def test_directory_expansion_covers_nested(repo):
    (repo / "src/sub").mkdir(parents=True)
    (repo / "src/sub/nested.py").write_text("x=1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "src", "reason": "whole src needed"}],
        session_digest=session_digest("src/sub/nested.py"),
    )
    assert result["passed"]
    assert "nested.py" not in str(result["blockers"])


def test_unrelated_expansion_does_not_cover(repo):
    (repo / "src").mkdir()
    (repo / "src/foo.py").write_text("x=1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "other", "reason": "unrelated"}],
        session_digest=session_digest("src/foo.py"),
    )
    assert not result["passed"]
    assert any("not covered by any scope-expansion" in b for b in result["blockers"])
    assert "src/foo.py" in result["out_of_scope_undeclared_files"]


def test_duplicate_expansion_warned(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[
            {"path": "other.py", "reason": "first"},
            {"path": "other.py", "reason": "duplicate"},
        ],
        session_digest=session_digest("other.py"),
    )
    assert result["passed"]
    assert any("duplicate" in w.lower() for w in result["warnings"])


def test_empty_expansion_path_validated(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "", "reason": "whoops"}],
        session_digest=session_digest("other.py"),
    )
    assert not result["passed"]
    assert any("path is empty" in b for b in result["blockers"])


def test_empty_expansion_path_warning_mode(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "warning", None, None, lambda: 0,
        scope_expansions=[{"path": "", "reason": "whoops"}],
        session_digest=session_digest("other.py"),
    )
    assert result["passed"]
    assert any("path is empty" in w for w in result["warnings"])


def test_expansion_path_escape_rejected(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "../escape", "reason": "bad"}],
        session_digest=session_digest("other.py"),
    )
    assert not result["passed"]
    assert any("invalid" in b.lower() for b in result["blockers"])


def test_unused_expansion_warned(repo):
    (repo / "legit.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["legit.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "untouched", "reason": "not needed"}],
        session_digest=session_digest("legit.py"),
    )
    assert result["passed"]
    assert any("did not cover any out-of-scope" in w for w in result["warnings"])


def test_expansions_ignored_when_no_expected_files(repo):
    (repo / "x.txt").write_text("x\n")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "x.txt", "reason": "present"}],
        session_digest=session_digest("x.txt"),
    )
    assert result["passed"]
    assert any("ignored because no expected_files" in w for w in result["warnings"])


def test_scope_expansions_declared_in_verdict(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "other.py", "reason": "needed",
                           "risk": "low", "validation": "tested"}],
        session_digest=session_digest("other.py"),
    )
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
        scope_expansions=[{"path": "x", "reason": "r"}],
        session_digest=session_digest("x"),
    )
    assert "scope_expansions_declared" in result
    assert "out_of_scope_undeclared_files" in result
    assert result["out_of_scope_undeclared_files"] == []
    assert result["scope_expansions_declared"] == [{"path": "x", "reason": "r"}]


def test_backward_compat_no_expansions_no_out_of_scope(repo):
    (repo / "x.txt").write_text("x\n")
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=session_digest("x.txt"),
    )
    assert result["passed"]
    assert result["scope_expansions_declared"] == []
    assert result["out_of_scope_undeclared_files"] == []


def test_scope_expanded_warning_when_accepted(repo):
    (repo / "other.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["expected.py"], "strict", None, None, lambda: 0,
        scope_expansions=[{"path": "other.py", "reason": "required"}],
        session_digest=session_digest("other.py"),
    )
    assert result["passed"]
    assert any("scope expanded to" in w for w in result["warnings"])


def test_session_edited_paths_normalized_to_repo_relative(repo):
    (repo / "a.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["a.py"], "strict", None, None, lambda: 0,
        session_digest=session_digest(str(repo / "a.py")),
    )
    assert result["task_changed_files"] == ["a.py"]


def test_session_edited_digest_round_trips(repo):
    (repo / "a.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["a.py"], "strict", None, None, lambda: 0,
        session_digest=session_digest(str(repo / "a.py"), digest="digest-a"),
    )
    assert result["task_changed_files"] == ["a.py"]
    assert result["task_diff_digest"] == "digest-a"


def test_session_edited_path_outside_repo_skipped(repo):
    (repo / "a.py").write_text("x = 1\n")
    result = review_repository(
        repo, ["a.py"], "strict", None, None, lambda: 0,
        session_digest=session_digest("/outside/repo/a.py"),
    )
    assert not result["passed"]
    assert any("no changes" in b.lower() for b in result["blockers"])


def test_observed_failed_warning_in_review(repo):
    (repo / "x.py").write_text("x = 1\n")
    digest = session_digest(
        "x.py",
        test_runs=[{"command": "pytest", "output": "2 failed"}],
    )
    result = review_repository(
        repo, [], "strict", None, None, lambda: 0,
        session_digest=digest,
    )
    assert any("observed failing tests" in w for w in result["warnings"])
