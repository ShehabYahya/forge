# Memory

Forge memory is the compounding layer behind the workflow. A task can leave a
finish receipt and a reusable lesson; later tasks get only the relevant active
cards back in context.

Forge memory has two distinct paths:

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

Finish-time creation is mandatory for every task that produces a reusable lesson (see the Forge Native Operating Protocol for exemptions). A card is created when the caller supplies `memory_draft` with concrete memory text (40-400 chars, must include a file path, function, or tool anchor, and avoid generic phrases), a why (20+ chars), and optionally an avoid field. Backend logic fills metadata such as card id, task ids, changed files, modules, transferability, and confidence. Invalid or generic drafts are rejected with warnings; task completion still succeeds.

## Feedback and scoring

When cards were injected into a task, `forge_finish_task` may also accept `memory_feedback` ratings for those exact card ids. Scoring combines task-success or failure outcomes from `task_finished` telemetry with a separately aggregated hidden agent rating. Missing feedback does not fail the task and is recorded as `memory_feedback_status: missing` in telemetry.

## Maintenance

Use `/review-memory` for card maintenance (edit, archive, restore, merge, compact, create_pattern_card, and create_memory_card). The installed plugin registers the command through its config hook and proxies requests through `forge_memory_review`; the packaged Markdown command remains a fallback distribution asset. The Python backend validates and applies batch operations. Archived cards stay out of normal task injection until explicitly restored.

The `create_memory_card` operation allows backfilling single-task memory cards from completed or failed task history. It requires exactly 1 source task id in a terminal state. The agent should check `memory_gaps` in the maintenance context for tasks that lack memory coverage.

Configuration overrides live in `~/.forge/config.json`. Memory maintenance settings use the nested `memory.maintenance.review` object; the earlier `memory.maintenance_review` spelling remains accepted for compatibility.

## Workflow role

```mermaid
flowchart LR
    A[finish receipt] --> B[memory_draft + feedback]
    B --> C[(active memory cards)]
    C --> D[start_task memory brief]
    D --> E[next task]
    C --> F[/review-memory]
    F --> C
```

The useful loop is narrow by design: finish creates or scores cards, start
injects relevant cards, and `/review-memory` keeps the card set sharp.

## See also

- [Contract](FORGE_CONTRACT.md) — the authoritative behavioral contract
- [Why Forge](WHY_FORGE.md) — why memory is part of the agent workflow harness
- [Context Governor](CONTEXT_GOVERNOR.md) — the maintenance-mode policy exception
- [Architecture](ARCHITECTURE.md) — storage layout
