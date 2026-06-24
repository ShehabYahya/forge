# Lifecycle

Start creates `active` and returns prepared context. At start, Forge captures a **baseline tree** snapshot of the worktree using a temporary Git index (the user's real index is never touched). The baseline status (`captured` or `unavailable`) is included in prepared context.

Review enters `reviewed` or `review_blocked`. Review compares the current worktree against the baseline tree to produce a **task delta** (files changed during the task) alongside pre-existing dirty files and the total worktree diff. Scope checks and the no-change blocker use the task delta. The staleness digest remains the total-worktree digest.

A successful finish requires `reviewed` plus an unchanged total-worktree Git digest and enters `completed`. Any edit after review makes that review stale — including edits to files the task never touched. A failed finish is always available from a nonterminal normal state and enters `failed`. Degraded fallback enters `degraded` and is never lifecycle completion.

## Baseline trees

Baseline trees are ephemeral, unreferenced objects in `.git/objects/`. Git's default GC grace period of two weeks covers all reasonable task lifetimes. If a tree object is missing at review time (e.g. after an aggressive manual `git gc`), the review falls back to the total-worktree diff with a warning.

## Review response fields

The review result includes both backward-compatible fields and new baseline-aware fields:

- `changed_files`, `diff_digest` — total worktree vs HEAD (preserved from prior versions)
- `task_changed_files`, `task_diff_digest` — task delta (baseline → current)
- `preexisting_dirty_files` — files dirty before task start (HEAD → baseline)
- `total_worktree_changed_files` — all dirty files (same as `changed_files`)
- `baseline_tree_id`, `current_tree_id` — tree SHAs (for debugging)
- `unexplained_changed_files`, `mutation_ledger_summary` — placeholders for future mutation ledger

## See also

- [Contract](FORGE_CONTRACT.md) — the authoritative behavioral contract
- [Architecture](ARCHITECTURE.md) — ownership split and data flow
- [Memory](MEMORY.md) — finish-time card creation and feedback

