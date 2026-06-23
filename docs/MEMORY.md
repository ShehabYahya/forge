# Memory

Forge memory now has two distinct paths:

1. `forge_finish_task` may create a new card from an explicit `memory_draft`.
2. `/review-memory` maintains the card set through the hidden maintenance backend.

## Storage

Runtime memory lives under `~/.forge/memory/`:

- `memory_cards.json`: active cards
- `memory_cards_deleted.json`: archived cards
- `memory_feedback.jsonl`: finish-time ratings on injected cards
- `memory_review_log.jsonl`: maintenance batch log
- `memory_id_counter.json`: global card id allocator

## Injection

Task start reads active cards only. Selection is deterministic, repo-scoped, bounded to 10 cards and 4,000 characters, and emits `[MEM mem_NNNNNN]` blocks with `memory`, `Why`, and `Avoid`.

## Finish-time creation

Finish-time creation is opt-in. A card is created only when the caller supplies `memory_draft`. Backend logic fills metadata such as card id, task ids, changed files, modules, transferability, and confidence. Invalid or generic drafts are rejected with warnings; task completion still succeeds.

## Feedback and scoring

When cards were injected into a task, `forge_finish_task` may also accept `memory_feedback` ratings for those exact card ids. Scoring combines task-success or failure outcomes from `task_finished` telemetry with a separately aggregated hidden agent rating. Missing feedback does not fail the task and is recorded as `memory_feedback_status: missing` in telemetry.

## Maintenance

Use `/review-memory` for card maintenance. The installed plugin registers the command through its config hook and proxies requests through `forge_memory_review`; the packaged Markdown command remains a fallback distribution asset. The Python backend validates and applies batch operations. Archived cards stay out of normal task injection until explicitly restored.

Configuration overrides live in `~/.forge/config.json`. Memory maintenance settings use the nested `memory.maintenance.review` object; the earlier `memory.maintenance_review` spelling remains accepted for compatibility.
