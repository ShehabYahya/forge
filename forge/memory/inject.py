from __future__ import annotations

from .cards import MemoryCard


def format_brief(ranked: list[tuple[int, MemoryCard]], max_cards: int = 10,
                 max_chars: int = 4000) -> str:
    selected: list[str] = []
    size = 0
    for _, card in ranked[:max_cards]:
        parts = [f"- {card.memory.strip()}"]
        if card.why:
            parts.append(f"  Why: {card.why.strip()}")
        if card.avoid:
            parts.append(f"  Avoid: {card.avoid.strip()}")
        if card.use_as:
            parts.append(f"  Use as: {card.use_as.strip()}")
        block = "\n".join(parts)
        separator = "\n" if selected else ""
        available = max_chars - size - len(separator)
        if available <= 0:
            break
        if len(block) > available:
            block = block[:available]
        selected.append(block)
        size += len(separator) + len(block)
        if size >= max_chars:
            break
    return "\n".join(selected)

