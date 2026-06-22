from __future__ import annotations

from typing import Any

from .cards import MemoryCard
from ..config import ScoringConfig

# Agent rating → numeric value mapping (spec lines 309).
RATING_VALUES: dict[str, float] = {
    "helpful": 1.0,
    "unused": 0.5,
    "misleading": 0.0,
    "unknown": 0.5,
}


def add_outcome_history(
    feedback_aggregate: dict[str, dict[str, int]],
    telemetry_events: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Combine agent ratings with independent injected-card task outcomes."""
    combined = {card_id: dict(bucket) for card_id, bucket in feedback_aggregate.items()}
    for record in telemetry_events:
        if record.get("event") != "task_finished":
            continue
        card_ids = record.get("injected_memory_cards")
        if not isinstance(card_ids, list):
            continue
        success = record.get("success") is True
        review_blocked = record.get("review_blocked") is True
        for card_id in card_ids:
            if not isinstance(card_id, str) or not card_id:
                continue
            bucket = combined.setdefault(card_id, {})
            key = "wins" if success and not review_blocked else "losses"
            bucket[key] = bucket.get(key, 0) + 1
    return combined


# --------------------------------------------------------------------- primitives


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _match_fraction(patterns: list[str], text: str) -> float:
    """Fraction of *patterns* found as case-insensitive substrings in *text*.

    Returns ``0.0`` when *patterns* is empty (no constraint → no contribution).
    """
    if not patterns:
        return 0.0
    haystack = text.lower()
    matched = sum(1 for p in patterns if p.lower() in haystack)
    return matched / len(patterns)


# ----------------------------------------------------------------------- scorings


def det_score(wins: int, losses: int) -> float:
    """Win-rate centred at 0.5 (spec lines 297-305).

    No history → ``0.5`` (neutral, not zero).
    """
    raw = 0.5 + 0.5 * (wins - losses) / max(1, wins + losses)
    return _clamp(raw)


def agent_score(
    card: MemoryCard,
    feedback_aggregate: dict[str, dict[str, int]],
    config: ScoringConfig,
) -> float:
    """Bayesian-shrunk agent rating (spec lines 307-318).

    Pure importable function — T6 imports this for the high-rated archive guard.

    ``prior = 0.5``, ``k = 2``.  ``n = aggregate[card_id]["n"]`` (0 if absent).
    Unrated (``n == 0``) → ``0.5``.
    """
    bucket = feedback_aggregate.get(card.card_id)
    if not bucket:
        return 0.5
    n = bucket.get("n", 0)
    if n == 0:
        return 0.5
    total = 0.0
    for rating, value in RATING_VALUES.items():
        total += value * bucket.get(rating, 0)
    prior = 0.5
    k = 2
    return (prior * k + total) / (k + n)


def relevance(
    card: MemoryCard,
    repo_id: str,
    task_text: str,
    expected_files: list[str],
    risks: list[str] | None = None,
) -> float:
    """Context-match relevance normalised to ``0..1`` (spec lines 332-343).

    Weights: task_types ×3, files ×2, risk_patterns ×3, repo ×5.
    Normalised by the max possible for *this card* (fields it actually declares).
    Repo mismatch → ``repo_match = 0`` here; ``select_cards`` applies the hard
    filter (drops the card entirely) before calling this.
    """
    aw = card.applies_when
    risks = risks or []

    task_match = _match_fraction(aw.task_types, task_text)
    file_match = _match_fraction(aw.files, " ".join(expected_files))
    risk_match = _match_fraction(aw.risk_patterns, " ".join(risks))
    repo_match = 1.0 if card.source_repo_id == repo_id else 0.0

    raw = 3.0 * task_match + 2.0 * file_match + 3.0 * risk_match + 5.0 * repo_match
    max_possible = (
        (3.0 if aw.task_types else 0.0)
        + (2.0 if aw.files else 0.0)
        + (3.0 if aw.risk_patterns else 0.0)
        + 5.0
    )
    if max_possible <= 0.0:
        return 0.0
    return raw / max_possible


def quality(
    card: MemoryCard,
    feedback_aggregate: dict[str, dict[str, int]],
    config: ScoringConfig,
) -> float:
    """Quality composite: ``w_det * det_score + w_agent * agent_score``.

    ``det_score`` uses task outcomes recorded independently in telemetry.
    """
    bucket = feedback_aggregate.get(card.card_id, {})
    wins = bucket.get("wins", 0)
    losses = bucket.get("losses", 0)
    return config.w_det * det_score(wins, losses) + config.w_agent * agent_score(
        card, feedback_aggregate, config
    )


def final_score(
    card: MemoryCard,
    feedback_aggregate: dict[str, dict[str, int]],
    config: ScoringConfig,
    repo_id: str,
    task_text: str,
    expected_files: list[str],
    risks: list[str] | None = None,
) -> float:
    """Final score: ``w_quality * quality + w_relevance * relevance``."""
    return (
        config.w_quality * quality(card, feedback_aggregate, config)
        + config.w_relevance * relevance(card, repo_id, task_text, expected_files, risks)
    )


# ------------------------------------------------------------------- selection


def select_cards(
    cards: list[MemoryCard],
    task: Any,
    feedback_aggregate: dict[str, dict[str, int]],
    config: ScoringConfig,
) -> list[str]:
    """Deterministic card selection with exploration slots (spec lines 345-362).

    *task* is any object with ``.repo_root``, ``.task_text``, ``.expected_files``
    (and optionally ``.risks``) — works with :class:`TaskSnapshot`.

    1. Hard-filter: ``source_repo_id == task.repo_root``.
    2. Split into rated (``n >= min_history``) and unrated (``n < min_history``).
    3. Fill ``max_cards - exploration_slots`` from rated, sorted by
       ``final desc, card_id asc``.
    4. Fill ``exploration_slots`` from unrated, sorted by
       ``relevance desc, card_id asc``.
    5. If unrated pool empty, backfill from remaining rated.

    Returns a ``list[card_id]`` — deterministic for identical inputs.
    """
    repo_id = task.repo_root
    task_text = task.task_text
    expected_files = task.expected_files
    risks = getattr(task, "risks", None)

    # 1. Repo hard-gate.
    eligible = [c for c in cards if c.source_repo_id == repo_id]

    # 2. Split by feedback history.
    rated: list[MemoryCard] = []
    unrated: list[MemoryCard] = []
    for c in eligible:
        n = feedback_aggregate.get(c.card_id, {}).get("n", 0)
        if n >= config.min_history:
            rated.append(c)
        else:
            unrated.append(c)

    # 3. Rated pool: final desc, card_id asc.
    rated_sorted = sorted(
        rated,
        key=lambda c: (
            -final_score(c, feedback_aggregate, config, repo_id, task_text, expected_files, risks),
            c.card_id,
        ),
    )

    # 4. Unrated pool: relevance desc, card_id asc.
    unrated_sorted = sorted(
        unrated,
        key=lambda c: (
            -relevance(c, repo_id, task_text, expected_files, risks),
            c.card_id,
        ),
    )

    main_slots = max(0, config.max_cards - config.exploration_slots)
    selected = rated_sorted[:main_slots]

    exploration = unrated_sorted[: config.exploration_slots]

    # 5. Backfill from rated when unrated pool is empty.
    if not unrated:
        remaining_rated = rated_sorted[main_slots:]
        exploration.extend(remaining_rated[: config.exploration_slots])

    selected.extend(exploration)

    # Cap at max_cards (safety; main_slots + exploration_slots == max_cards by
    # default, but guard against config edge cases).
    selected = selected[: config.max_cards]
    return [c.card_id for c in selected]
