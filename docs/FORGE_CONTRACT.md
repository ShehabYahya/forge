# Forge Contract

The authoritative behavioral contract for Forge. For the system design and data
flow, see [Architecture](ARCHITECTURE.md). For the step-by-step states, see
[Lifecycle](LIFECYCLE.md).

## Identity and trust boundary

Forge is a local proof layer with an explicit ownership split. Python is authoritative for lifecycle, review, memory, task-owned MCP result retrieval, telemetry, and memory-maintenance decisions. The OpenCode TypeScript plugin is authoritative for host-tool policy, native host permission escalation, duplicate-read detection, and proxying `/review-memory` requests to the hidden Python maintenance backend.

## Public MCP surface

Exactly five agent-visible tools are public: `forge_start_task`, `forge_review_changes`, `forge_finish_task`, `forge_submit_outcome`, and `forge_expand_tool_result`. In OpenCode these names come from MCP server key `forge` plus bare MCP tool names `start_task`, `review_changes`, `finish_task`, `submit_outcome`, and `expand_tool_result`. The old `forge-alpha_forge_*` names and direct bare MCP names are not the public surface. `forge_prepare_context` is removed, not deprecated; start is the sole preparation entry point. Begin-task aliases, memory administration, and plugin protocol operations are not public.

Every response includes `schema_version`, `ok`, `task_id`, `state`, `warnings`, and `required_next_action`. Finish-task responses additionally include `lifecycle_verified`, `verification_basis`, `mutation_capture_status`, `validation_status`, `claim_honesty`, and `lifecycle_complete`. The legacy `verified` field is a deprecated alias of `lifecycle_verified`.

## Lifecycle

Persisted states are `active`, `review_blocked`, `reviewed`, `completed`, `failed`, and `degraded`. Review accepts active or nonterminal review states. A passing review records the current session-owned edit digest. Successful finish requires reviewed state and the same current session digest. Failed finish is accepted from any nonterminal normal state. Terminal calls are idempotent and do not emit duplicate terminal events. Degraded fallback is unverified, lifecycle-incomplete, and cannot become normally completed.

Review is session-log-backed, not Git-diff-backed. Scope checks and the no-change blocker use `session_digest.edited_files`. Freshness uses `session_digest.edited_files_digest`, which must change whenever the host logs another edit or write event. If session evidence is missing, Forge cannot verify successful completion and must route the task to degraded outcome rather than silently trusting the final message.

Agent-reported validation remains reported unless Forge has direct transcript or runtime evidence for it. Review observes session-owned changed files, scope, readable content, Python syntax, and recorded validation evidence; it does not prove semantic correctness. Failure is explicit and unsupported behavior is never presented as success.

Lifecycle enforcement is owned by the Python service responses, not by an automatic plugin task state machine. The OpenCode plugin does not create a task, inject a mandatory lifecycle prompt, or reject every mutation performed without a bound task. Agents and integrations must call the public lifecycle tools explicitly.

The injected operating prompt classifies substantive work and gates heavier implementation with the Independent Review Loop. Tiny fast-path edits do not require it. Controlled implementation work does: before editing, the agent must write a plan and delegate a read-only independent plan review to a subagent, looping until it passes; after editing and validation, the agent must delegate a read-only independent implementation review to a subagent, looping until it passes. The plan review runs regardless of whether the user already reviewed or approved the plan. Reviews must be delegated to a subagent — self-review does not satisfy the loop. The Independent Review Loop is separate from and independent of `forge_review_changes`; passing one does not skip the other. Forge's own `forge_review_changes` remains required before successful finish for mutation tasks and is not a substitute for the Independent Review Loop.

## Storage and context

Runtime data lives under `~/.forge/` unless explicitly overridden and never in the controlled repository. The governor has off, report, and active modes. Duplicate reads are tracked per host session. Dangerous commands and cross-repository access escalate through OpenCode's native permission system rather than being converted into permanent plugin errors. The plugin preserves an existing host `deny`, installs `ask` rules for its dangerous-command set, and does not copy the old Forge MCP command allowlist into host-tool policy.

`forge_expand_tool_result` is an MCP storage API for task-owned `fr_` handles. It allows at most 16,000 characters per call and 32,000 characters cumulatively per handle. No standard production flow currently produces an `fr_` handle for this MCP endpoint. The endpoint remains in the five-tool contract as a compatibility surface.

Memory cards are stored under `~/.forge/memory/` as deterministic JSON/JSONL artifacts. Successful `forge_finish_task` calls create a new card from a mandatory `memory_draft` (except for the documented exemptions: mismatch, degraded, or no-lesson-with-explicit-reason). Finish-time feedback may score previously injected cards, but outcomes never edit or archive existing cards. Runtime injection selects active cards deterministically and archived cards are invisible to normal task starts.

Maintenance happens through `/review-memory`, which the installed plugin registers and backs with a thin bridge to the Python maintenance service. It requires no active lifecycle task. During that mode the plugin applies the backend-provided tool allowlist deny-by-default and bypasses governor policy. The `forge_memory_review` plugin tool proxies validated edit, archive, restore, merge, compact, cross-task pattern, and single-task memory operations. The `memory_gaps` analysis identifies terminal tasks that lack memory card coverage.

## Non-goals

No embeddings, semantic graph, learning loop, retry controller, autonomous orchestration, Goal Mode, benchmark product, process virtualization, container management, or semantic correctness verification is included.

Stored host outputs currently have no TTL or garbage collector. Expansion and search load the stored output into memory before selecting the requested content; this is acceptable for the alpha target but is not a streaming implementation.

## See also

- [Architecture](ARCHITECTURE.md) — ownership split and data flow
- [Receipts](RECEIPTS.md) — what Forge records when agent work finishes
- [Lifecycle](LIFECYCLE.md) — states and session-backed review fields
- [Memory](MEMORY.md) — cards, injection, feedback, maintenance
- [Context Governor](CONTEXT_GOVERNOR.md) — host-tool policy and safety friction
