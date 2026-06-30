"""Tests for forge.memory.scoring — det_score, agent_score, relevance,
quality, final_score, select_cards — and the rewritten format_brief.

These tests exercise the spec formulas (spec lines 262-383) directly.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from forge.config import ScoringConfig, default_config
from forge.memory.cards import AppliesWhen, MemoryCard
from forge.memory.inject import format_brief
from forge.memory.scoring import (
    RATING_VALUES,
    add_outcome_history,
    agent_score,
    det_score,
    final_score,
    quality,
    relevance,
    select_cards,
)


# ----------------------------------------------------------------- helpers


def card(card_id="mem_000001", **values):
    defaults = {
        "card_id": card_id,
        "memory": f"memory {card_id}",
        "why": "",
        "avoid": "",
        "use_as": "",
        "entry_type": "validation_memory",
        "transferability": "local_only",
        "source_repo_root": "/repo",
        "source_repo_id": "/repo",
        "applies_when": AppliesWhen(),
        "confidence": "medium",
        "source_task_ids": [],
        "supersedes": [],
        "superseded_by": None,
        "created_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(values)
    return MemoryCard(**defaults)


def cfg() -> ScoringConfig:
    return default_config().memory.scoring


def task(repo="/repo", text="fix bug", files=None, risks=None):
    return SimpleNamespace(
        repo_root=repo, task_text=text, expected_files=files or [], risks=risks
    )


def agg(*entries):
    """Build a feedback aggregate from (card_id, helpful, unused, misleading, unknown)."""
    out = {}
    for cid, h, u, m, unk in entries:
        out[cid] = {
            "helpful": h,
            "unused": u,
            "misleading": m,
            "unknown": unk,
            "n": h + u + m + unk,
        }
    return out


# ================================================================ det_score


class TestDetScore:
    def test_no_history_is_neutral(self):
        assert det_score(0, 0) == 0.5

    def test_wins_exceed_losses_above_neutral(self):
        assert det_score(3, 1) == pytest.approx(0.75)

    def test_all_wins_is_one(self):
        assert det_score(4, 0) == 1.0

    def test_all_losses_is_zero(self):
        assert det_score(0, 4) == 0.0

    def test_equal_wins_losses_is_neutral(self):
        assert det_score(2, 2) == 0.5

    def test_clamped_to_unit_interval(self):
        assert 0.0 <= det_score(0, 100) <= 1.0
        assert 0.0 <= det_score(100, 0) <= 1.0


# ================================================================ agent_score


class TestAgentScore:
    def test_unrated_card_is_neutral(self):
        c = card("mem_000001")
        assert agent_score(c, {}, cfg()) == 0.5

    def test_unrated_card_missing_n_is_neutral(self):
        c = card("mem_000001")
        assert agent_score(c, {"mem_000001": {"n": 0}}, cfg()) == 0.5

    def test_helpful_ratings_pull_up(self):
        c = card("mem_000001")
        a = agg(("mem_000001", 3, 0, 0, 0))
        # (0.5*2 + 3*1.0) / (2+3) = 4/5 = 0.8
        assert agent_score(c, a, cfg()) == pytest.approx(0.8)

    def test_misleading_ratings_pull_down(self):
        c = card("mem_000001")
        a = agg(("mem_000001", 0, 0, 2, 0))
        # (0.5*2 + 2*0.0) / (2+2) = 1/4 = 0.25
        assert agent_score(c, a, cfg()) == pytest.approx(0.25)

    def test_bayesian_shrinkage_prior_fades(self):
        c = card("mem_000001")
        a1 = agg(("mem_000001", 1, 0, 0, 0))
        a5 = agg(("mem_000001", 5, 0, 0, 0))
        score1 = agent_score(c, a1, cfg())
        score5 = agent_score(c, a5, cfg())
        assert score1 < score5
        assert score1 == pytest.approx(2 / 3, abs=1e-6)
        assert score5 == pytest.approx(6 / 7, abs=1e-6)

    def test_mixed_helpful_misleading(self):
        c = card("mem_000001")
        a = agg(("mem_000001", 1, 0, 1, 0))
        # (0.5*2 + 1.0 + 0.0) / (2+2) = 2/4 = 0.5
        assert agent_score(c, a, cfg()) == 0.5

    def test_unused_is_neutral_rating(self):
        c = card("mem_000001")
        a = agg(("mem_000001", 0, 3, 0, 0))
        # (0.5*2 + 3*0.5) / (2+3) = 2.5/5 = 0.5
        assert agent_score(c, a, cfg()) == 0.5

    def test_rating_values_mapping(self):
        assert RATING_VALUES == {
            "helpful": 1.0,
            "unused": 0.5,
            "misleading": 0.0,
            "unknown": 0.5,
        }


# ================================================================ relevance


class TestRelevance:
    def test_same_repo_no_patterns_is_perfect(self):
        c = card("mem_000001", source_repo_id="/repo", applies_when=AppliesWhen())
        assert relevance(c, "/repo", "anything", []) == 1.0

    def test_repo_mismatch_zero_repo_term(self):
        c = card("mem_000001", source_repo_id="/other")
        assert relevance(c, "/repo", "anything", []) == 0.0

    def test_task_type_match_increases_relevance(self):
        c_match = card("mem_000001", applies_when=AppliesWhen(task_types=["bug"]))
        c_no = card("mem_000002", applies_when=AppliesWhen(task_types=["refactor"]))
        r_match = relevance(c_match, "/repo", "fix a bug", [])
        r_no = relevance(c_no, "/repo", "fix a bug", [])
        assert r_match > r_no
        assert r_match == 1.0
        assert r_no == pytest.approx(5 / 8)

    def test_file_match_increases_relevance(self):
        c = card("mem_000001", applies_when=AppliesWhen(files=["forge/service.py"]))
        r_match = relevance(c, "/repo", "task", ["forge/service.py"])
        r_no = relevance(c, "/repo", "task", ["other/file.py"])
        assert r_match > r_no
        assert r_match == 1.0

    def test_risk_match_increases_relevance(self):
        c = card("mem_000001", applies_when=AppliesWhen(risk_patterns=["scope drift"]))
        r_match = relevance(c, "/repo", "task", [], risks=["scope drift"])
        r_no = relevance(c, "/repo", "task", [], risks=["performance"])
        assert r_match > r_no
        assert r_match == 1.0

    def test_partial_task_match(self):
        c = card(
            "mem_000001",
            applies_when=AppliesWhen(task_types=["bug", "refactor"]),
        )
        # 1 of 2 patterns match → task_match = 0.5
        # raw = 3*0.5 + 5 = 6.5, max = 3 + 5 = 8 → 0.8125
        r = relevance(c, "/repo", "fix a bug", [])
        assert r == pytest.approx(6.5 / 8)

    def test_no_risks_argument_treated_as_empty(self):
        c = card("mem_000001", applies_when=AppliesWhen(risk_patterns=["x"]))
        assert relevance(c, "/repo", "task", [], risks=None) == relevance(
            c, "/repo", "task", [], risks=[]
        )


# ================================================================ quality / final


class TestQualityFinal:
    def test_empty_aggregate_quality_is_half(self):
        c = card("mem_000001")
        assert quality(c, {}, cfg()) == 0.5

    def test_empty_aggregate_final_same_repo_no_patterns(self):
        c = card("mem_000001", source_repo_id="/repo")
        assert final_score(c, {}, cfg(), "/repo", "task", []) == pytest.approx(0.65)

    def test_helpful_card_higher_final_than_misleading(self):
        c = card("mem_000001", source_repo_id="/repo")
        a_good = agg(("mem_000001", 5, 0, 0, 0))
        a_bad = agg(("mem_000001", 0, 0, 5, 0))
        good = final_score(c, a_good, cfg(), "/repo", "task", [])
        bad = final_score(c, a_bad, cfg(), "/repo", "task", [])
        assert good > bad

    def test_deterministic_score_uses_telemetry_not_agent_rating(self):
        c = card("mem_000001", source_repo_id="/repo")
        feedback = agg(("mem_000001", 0, 0, 5, 0))
        combined = add_outcome_history(feedback, [{
            "event": "task_finished",
            "success": True,
            "injected_memory_cards": ["mem_000001"],
        }])
        assert combined["mem_000001"]["wins"] == 1
        expected = cfg().w_det * 1.0 + cfg().w_agent * agent_score(c, feedback, cfg())
        assert quality(c, combined, cfg()) == pytest.approx(expected)


# ================================================================ select_cards


class TestSelectCards:
    def test_repo_mismatch_excluded(self):
        cards = [
            card("mem_000001", source_repo_id="/repo"),
            card("mem_000002", source_repo_id="/other"),
        ]
        ids = select_cards(cards, task(), {}, cfg())
        assert ids == ["mem_000001"]

    def test_deterministic_same_input_same_output(self):
        cards = [
            card("mem_000003", applies_when=AppliesWhen(task_types=["bug"])),
            card("mem_000001", applies_when=AppliesWhen(task_types=["bug"])),
            card("mem_000002", applies_when=AppliesWhen(task_types=["bug"])),
        ]
        t = task(text="fix bug")
        ids1 = select_cards(cards, t, {}, cfg())
        ids2 = select_cards(cards, t, {}, cfg())
        assert ids1 == ids2

    def test_card_id_tiebreak_for_equal_final(self):
        c1 = card("mem_000003", source_repo_id="/repo")
        c2 = card("mem_000001", source_repo_id="/repo")
        a = agg(("mem_000001", 2, 0, 0, 0), ("mem_000003", 2, 0, 0, 0))
        ids = select_cards([c1, c2], task(), a, cfg())
        assert ids == ["mem_000001", "mem_000003"]

    def test_rated_pool_fills_main_slots(self):
        cards = [
            card("mem_000001", source_repo_id="/repo"),
            card("mem_000002", source_repo_id="/repo"),
            card("mem_000003", source_repo_id="/repo"),
            card("mem_000004", source_repo_id="/repo"),
        ]
        a = agg(
            ("mem_000001", 2, 0, 0, 0),
            ("mem_000002", 2, 0, 0, 0),
            ("mem_000003", 2, 0, 0, 0),
        )
        ids = select_cards(cards, task(), a, cfg())
        assert ids == ["mem_000001", "mem_000002", "mem_000003", "mem_000004"]

    def test_rated_ordering_by_final_desc(self):
        cards = [
            card("mem_000001", source_repo_id="/repo"),
            card("mem_000002", source_repo_id="/repo"),
        ]
        a = agg(("mem_000001", 5, 0, 0, 0), ("mem_000002", 0, 0, 5, 0))
        ids = select_cards(cards, task(), a, cfg())
        assert ids == ["mem_000001", "mem_000002"]

    def test_unrated_cards_fill_all_slots(self):
        """Unrated cards compete in the same pool — when eligible < max_cards, all fill."""
        cards = [
            card("mem_000001", source_repo_id="/repo"),
            card("mem_000002", source_repo_id="/repo"),
            card("mem_000003", source_repo_id="/repo"),
            card("mem_000004", source_repo_id="/repo"),
            card("mem_000005", source_repo_id="/repo"),
        ]
        a = agg(("mem_000001", 2, 0, 0, 0), ("mem_000002", 2, 0, 0, 0))
        ids = select_cards(cards, task(), a, cfg())
        assert ids == ["mem_000001", "mem_000002", "mem_000003", "mem_000004", "mem_000005"]

    def test_backfill_when_unrated_empty(self):
        cards = [
            card("mem_000001", source_repo_id="/repo"),
            card("mem_000002", source_repo_id="/repo"),
            card("mem_000003", source_repo_id="/repo"),
            card("mem_000004", source_repo_id="/repo"),
            card("mem_000005", source_repo_id="/repo"),
        ]
        a = agg(
            ("mem_000001", 2, 0, 0, 0),
            ("mem_000002", 2, 0, 0, 0),
            ("mem_000003", 2, 0, 0, 0),
            ("mem_000004", 2, 0, 0, 0),
            ("mem_000005", 2, 0, 0, 0),
        )
        ids = select_cards(cards, task(), a, cfg())
        assert ids == ["mem_000001", "mem_000002", "mem_000003", "mem_000004", "mem_000005"]

    def test_backfill_from_remaining_rated(self):
        cards = [card(f"mem_{i:06d}", source_repo_id="/repo") for i in range(1, 13)]
        a = {
            f"mem_{i:06d}": {"helpful": 2, "unused": 0, "misleading": 0, "unknown": 0, "n": 2}
            for i in range(1, 13)
        }
        ids = select_cards(cards, task(), a, cfg())
        # 12 cards, 0 unrated.  Top 10 by final_score → mem_000001..mem_000010.
        # mem_000011, mem_000012 dropped.
        assert ids == [f"mem_{i:06d}" for i in range(1, 11)]
        assert len(ids) == 10

    def test_max_cards_respected(self):
        cards = [card(f"mem_{i:06d}", source_repo_id="/repo") for i in range(1, 21)]
        ids = select_cards(cards, task(), {}, cfg())
        assert len(ids) <= cfg().max_cards

    def test_unrated_sorted_by_relevance_desc(self):
        c_low = card(
            "mem_000001",
            applies_when=AppliesWhen(task_types=["refactor"]),
        )
        c_high = card(
            "mem_000002",
            applies_when=AppliesWhen(task_types=["bug"]),
        )
        t = task(text="fix bug")
        ids = select_cards([c_low, c_high], t, {}, cfg())
        # Both unrated; c_high matches "bug" → higher relevance → first.
        assert ids == ["mem_000002", "mem_000001"]

    def test_empty_input_returns_empty(self):
        assert select_cards([], task(), {}, cfg()) == []


    def test_transferable_cards_bypass_repo_filter(self):
        """Cards with source_repo_id='*' (cross-task patterns) match any repo."""
        transferable_card = card(
            "mem_pattern_001",
            source_repo_id="*",
            source_repo_root="*",
            transferability="transferable",
            entry_type="cross_task_pattern",
            memory="pattern: always pass runtime_root to load_config()",
        )
        local_card = card(
            "mem_local_001",
            source_repo_id="/other-repo",
            source_repo_root="/other-repo",
            memory="specific to other repo",
        )
        # Transferable card matches, local does not.
        ids = select_cards([transferable_card, local_card], task(), {}, cfg())
        assert "mem_pattern_001" in ids
        assert "mem_local_001" not in ids


# ================================================================ format_brief


class TestFormatBrief:
    def test_mem_prefix_and_fields(self):
        ranked = [(0, card("mem_000001", memory="verify tool lists separately",
                            why="past changes mixed public and plugin helpers",
                            avoid="documenting plugin-only helpers as public"))]
        brief = format_brief(ranked)
        assert "[MEM mem_000001]" in brief
        assert "verify tool lists separately" in brief
        assert "Why: past changes mixed public and plugin helpers" in brief
        assert "Avoid: documenting plugin-only helpers as public" in brief

    def test_no_use_as_in_output(self):
        ranked = [(0, card("mem_000001", use_as="reference during planning"))]
        brief = format_brief(ranked)
        assert "Use as:" not in brief
        assert "reference during planning" not in brief

    def test_no_scores_or_metadata_in_output(self):
        c = card("mem_000001", confidence="high", source_task_ids=["task_1"],
                 supersedes=["mem_old"], memory="some lesson")
        ranked = [(750, c)]
        brief = format_brief(ranked)
        assert "750" not in brief
        assert "high" not in brief
        assert "task_1" not in brief
        assert "mem_old" not in brief

    def test_blank_line_between_cards(self):
        ranked = [
            (0, card("mem_000001", memory="first lesson", why="reason one")),
            (0, card("mem_000002", memory="second lesson", why="reason two")),
        ]
        brief = format_brief(ranked)
        assert "\n\n[MEM mem_000002]" in brief

    def test_max_cards_limit(self):
        ranked = [(0, card(f"mem_{i:06d}", memory=f"lesson {i}"))
                  for i in range(20)]
        brief = format_brief(ranked, max_cards=5)
        count = brief.count("[MEM ")
        assert count == 5

    def test_format_brief_includes_all_cards(self):
        ranked = [(0, card("mem_000001", memory="x" * 500)) for _ in range(20)]
        brief = format_brief(ranked, max_cards=10)
        count = brief.count("[MEM ")
        assert count == 10

    def test_deterministic(self):
        ranked = [(0, card(f"mem_{i:06d}", memory=f"note {i}"))
                  for i in range(10)]
        b1 = format_brief(ranked)
        b2 = format_brief(ranked)
        assert b1 == b2

    def test_empty_input_returns_empty_string(self):
        assert format_brief([]) == ""

    def test_omits_blank_why_avoid_when_empty(self):
        ranked = [(0, card("mem_000001", memory="just a lesson", why="", avoid=""))]
        brief = format_brief(ranked)
        assert "Why:" not in brief
        assert "Avoid:" not in brief
        assert "[MEM mem_000001]" in brief
        assert "just a lesson" in brief
