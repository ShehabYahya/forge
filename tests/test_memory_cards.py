import json

import pytest

from forge.memory.cards import MemoryCard
from forge.memory.inject import format_brief
from forge.memory.store import MemoryStore, rank


def card(card_id="a", **values):
    defaults = {"card_id": card_id, "memory": f"memory {card_id}", "repo_id": "/repo",
                "created_at": "2026-01-01T00:00:00Z"}
    defaults.update(values)
    return MemoryCard(**defaults)


def test_schema_round_trip_and_validation():
    value = card(priority=10)
    assert MemoryCard.from_dict(value.to_dict()) == value
    with pytest.raises(ValueError):
        card(priority=11)


def test_superseding_corrupt_and_disabled_records(tmp_path):
    path = tmp_path / "cards.jsonl"
    store = MemoryStore(path)
    store.append_manual(card(memory="old"))
    with path.open("a") as stream:
        stream.write("{bad}\n")
    store.append_manual(card(memory="new"))
    store.append_manual(card("disabled", enabled=False))
    cards, warnings = store.load()
    assert next(item for item in cards if item.card_id == "a").memory == "new"
    assert warnings
    assert [item.card_id for _, item in rank(cards, "/repo", "task", [])] == ["a"]


def test_ranking_is_repo_isolated_stable_and_bounded():
    cards = [card("b", task_keywords=["fix"], priority=1),
             card("a", task_keywords=["fix"], priority=1),
             card("other", repo_id="/other", priority=10)]
    ranked = rank(cards, "/repo", "fix bug", [])
    assert [item.card_id for _, item in ranked] == ["a", "b"]
    brief = format_brief(ranked * 10, max_cards=10, max_chars=40)
    assert len(brief) <= 40
    assert brief == format_brief(ranked * 10, max_cards=10, max_chars=40)


def test_lifecycle_does_not_write_memory(service, repo):
    task_id = service.forge_start_task("task", str(repo))["task_id"]
    service.forge_finish_task(task_id, False, "failed")
    assert not (service.runtime_root / "memory" / "cards.jsonl").exists()

