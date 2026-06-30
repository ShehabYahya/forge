# Lifecycle

Start creates `active` and returns prepared context. Prepared context still includes `baseline_status` for compatibility, but review no longer captures or uses a Git baseline tree. The field is now informational only (`not_used`).

Review enters `reviewed` or `review_blocked`. Review now uses the host-provided `session_digest` as the source of truth for task-owned mutations. Scope checks and the no-change blocker use `session_digest.edited_files`. The staleness digest is `session_digest.edited_files_digest`.

A successful finish requires `reviewed` plus an unchanged session digest and enters `completed`. Any additional logged edit after review makes that review stale, including another edit to the same file. If Forge lacks usable session evidence, successful finish cannot be verified and must take the degraded path instead. A failed finish is always available from a nonterminal normal state and enters `failed`. Degraded fallback enters `degraded` and is never lifecycle completion.

## Session evidence

Forge review depends on host session logs. A supported adapter must provide:

- `edited_files` — the deduplicated set of session-touched files, normalized to repo-relative paths
- `edited_files_digest` — a digest over the ordered edit/write event stream, used for freshness checks
- `test_runs` — optional observed validation commands and outputs

If these fields are missing, Forge reports a capability-limited review and cannot verify a successful finish.

## Review response fields

The review result includes both active fields and compatibility placeholders:

- `changed_files`, `diff_digest` — session-owned changed files and session digest
- `task_changed_files`, `task_diff_digest` — same values as the active review surface
- `preexisting_dirty_files` — always empty under the session-log model
- `total_worktree_changed_files` — same as `changed_files`
- `baseline_tree_id`, `current_tree_id` — always `null`
- `unexplained_changed_files`, `mutation_ledger_summary` — placeholders for future mutation ledger

## See also

- [Contract](FORGE_CONTRACT.md) — the authoritative behavioral contract
- [Architecture](ARCHITECTURE.md) — ownership split and data flow
- [Memory](MEMORY.md) — finish-time card creation and feedback
