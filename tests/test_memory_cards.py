from __future__ import annotations

import pytest

from forge.memory.cards import AppliesWhen, MemoryCard
from forge.memory.inject import format_brief
from forge.memory.store import MemoryStore, rank


def card(card_id="a", **values):
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


def test_card_round_trip_to_dict_from_dict():
    original = card(
        applies_when=AppliesWhen(task_types=["tooling"], files=["forge/service.py"],
                                  modules=["forge"], risk_patterns=["scope drift"]),
        source_task_ids=["task_1", "task_2"],
        supersedes=["mem_000001"],
        use_as="reference during planning",
        why="past regressions here",
        avoid="editing without tests",
    )
    data = original.to_dict()
    assert data["applies_when"] == {
        "task_types": ["tooling"],
        "files": ["forge/service.py"],
        "modules": ["forge"],
        "risk_patterns": ["scope drift"],
    }
    assert data["schema_version"] == 1
    assert data["superseded_by"] is None
    rebuilt = MemoryCard.from_dict(data)
    assert rebuilt == original


def test_applies_when_nested_in_to_dict():
    aw = AppliesWhen(task_types=["docs"], files=["a.py"], modules=["m"], risk_patterns=["r"])
    data = card(applies_when=aw).to_dict()
    assert isinstance(data["applies_when"], dict)
    assert data["applies_when"]["task_types"] == ["docs"]
    assert data["applies_when"]["files"] == ["a.py"]
    assert data["applies_when"]["modules"] == ["m"]
    assert data["applies_when"]["risk_patterns"] == ["r"]


def test_from_dict_tolerates_missing_optional_keys():
    minimal = {
        "card_id": "mem_000001",
        "memory": "a valid memory note",
        "entry_type": "validation_memory",
        "transferability": "local_only",
        "source_repo_root": "/repo",
        "source_repo_id": "/repo",
        "confidence": "medium",
        "created_at": "2026-01-01T00:00:00Z",
    }
    rebuilt = MemoryCard.from_dict(minimal)
    assert rebuilt.why == ""
    assert rebuilt.avoid == ""
    assert rebuilt.use_as == ""
    assert rebuilt.source_task_ids == []
    assert rebuilt.supersedes == []
    assert rebuilt.superseded_by is None
    assert rebuilt.schema_version == 1
    assert rebuilt.applies_when == AppliesWhen()


@pytest.mark.parametrize("bad_field,bad_value", [
    ("entry_type", "bad_type"),
    ("transferability", "global"),
    ("confidence", "sure"),
])
def test_enum_validation_rejects_bad_values(bad_field, bad_value):
    with pytest.raises(ValueError):
        card(**{bad_field: bad_value})


def test_bad_created_at_rejected():
    with pytest.raises(ValueError):
        card(created_at="not-a-date")


def test_non_str_list_fields_rejected():
    with pytest.raises(ValueError):
        card(source_task_ids=["ok", 3])
    with pytest.raises(ValueError):
        card(supersedes=[1])
    with pytest.raises(ValueError):
        card(applies_when=AppliesWhen(task_types=["ok", 5]))


def test_empty_memory_rejected():
    with pytest.raises(ValueError):
        card(memory="   ")


def test_rank_is_repo_isolated_and_deterministic():
    """The rank shim excludes cards from other repos and orders deterministically."""
    cards = [
        card("mem_000003", source_repo_id="/repo"),
        card("mem_000001", source_repo_id="/repo"),
        card("mem_000002", source_repo_id="/other"),
    ]
    ranked = rank(cards, "/repo", "fix bug", ["a.py"])
    assert [c.card_id for _, c in ranked] == ["mem_000001", "mem_000003"]
    assert all(c.source_repo_id == "/repo" for _, c in ranked)
    # Scores are non-zero (scoring-backed, not the old placeholder 0).
    assert all(score > 0 for score, _ in ranked)
    # Equal-relevance cards (no applies_when patterns, same repo) get equal scores.
    assert ranked[0][0] == ranked[1][0]


def test_rank_ignores_risks_when_no_risk_patterns():
    cards = [card("mem_000001", source_repo_id="/repo")]
    ranked_no_risks = rank(cards, "/repo", "task", [])
    ranked_with_risks = rank(cards, "/repo", "task", [], risks=["scope"])
    assert ranked_no_risks == ranked_with_risks


def test_format_brief_still_works_with_new_card():
    ranked = [(0, card("mem_000001", memory="edit forge/config.py to pass runtime_root",
                       why="past changes missed the override path",
                       avoid="hardcoding the home directory",
                       use_as="reference when touching config loading"))]
    brief = format_brief(ranked, max_cards=10, max_chars=4000)
    assert "[MEM mem_000001]" in brief
    assert "edit forge/config.py" in brief
    assert "Why:" in brief
    assert "Avoid:" in brief
    # Q2 decision: use_as is dropped from injected text.
    assert "Use as:" not in brief
    assert "reference when touching config loading" not in brief
    assert len(brief) <= 4000


def test_format_brief_bounded_and_deterministic():
    ranked = [(0, card("mem_%06d" % i, memory="note %d about forge/service.py" % i))
              for i in range(20)]
    brief = format_brief(ranked, max_cards=10, max_chars=200)
    assert len(brief) <= 200
    assert brief == format_brief(ranked, max_cards=10, max_chars=200)


def test_lifecycle_does_not_write_memory(service, repo):
    task_id = service.forge_start_task("task", str(repo))["task_id"]
    service.forge_finish_task(task_id, False, "failed")
    assert not (service.runtime_root / "memory" / "memory_cards.json").exists()
