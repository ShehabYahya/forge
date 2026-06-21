from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .cards import MemoryCard


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[list[MemoryCard], list[str]]:
        latest: dict[str, MemoryCard] = {}
        warnings: list[str] = []
        if not self.path.exists():
            return [], warnings
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return [], [f"memory read failed: {exc}"]
        for number, line in enumerate(lines, 1):
            try:
                card = MemoryCard.from_dict(json.loads(line))
                latest[card.card_id] = card
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                warnings.append(f"skipped corrupt memory card at line {number}: {exc}")
        return list(latest.values()), warnings

    def append_manual(self, card: MemoryCard) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(card.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")


def tokens(text: str) -> set[str]:
    return {part for part in "".join(char.lower() if char.isalnum() else " " for char in text).split() if part}


def matches(pattern: str, text: str, text_tokens: set[str]) -> bool:
    lowered = pattern.lower().strip()
    return bool(lowered) and (lowered in text.lower() or lowered in text_tokens)


def rank(cards: Iterable[MemoryCard], repo_id: str, task_text: str,
         files: list[str], risks: list[str] | None = None) -> list[tuple[int, MemoryCard]]:
    task_tokens = tokens(task_text)
    file_text = " ".join(files)
    file_tokens = tokens(file_text)
    risk_text = " ".join(risks or [])
    risk_tokens = tokens(risk_text)
    ranked: list[tuple[int, MemoryCard]] = []
    for card in cards:
        if not card.enabled or card.repo_id != repo_id:
            continue
        score = card.priority
        score += 3 * sum(matches(item, task_text, task_tokens) for item in card.task_keywords)
        score += 2 * sum(matches(item, file_text, file_tokens) for item in card.file_patterns)
        score += 3 * sum(matches(item, risk_text, risk_tokens) for item in card.risk_patterns)
        ranked.append((score, card))
    return sorted(ranked, key=lambda item: (-item[0], item[1].card_id))

