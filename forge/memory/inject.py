from __future__ import annotations

from .cards import MemoryCard


def format_brief(
    ranked: list[tuple[int, MemoryCard]],
    max_cards: int = 10,
) -> str:
    """Render memory cards as the injected ``memory_brief`` string.

    Keeps the ``list[tuple[int, MemoryCard]]`` signature that ``service.py``
    passes (the int score is ignored — ordering is already established by the
    caller).

    Per-card block (spec lines 120-131, 364-383)::

        [MEM mem_000001]
        memory text
        Why: ...
        Avoid: ...

    Blocks are separated by a blank line.  Never includes ``use_as``, scores,
    ratings, confidence, counters, source_task_ids, supersedes, or storage
    paths.  Honours ``max_cards``.
    """
    blocks: list[str] = []
    for _, card in ranked[:max_cards]:
        lines = [f"[MEM {card.card_id}]"]
        memory = card.memory.strip()
        if memory:
            lines.append(memory)
        why = card.why.strip()
        if why:
            lines.append(f"Why: {why}")
        avoid = card.avoid.strip()
        if avoid:
            lines.append(f"Avoid: {avoid}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
