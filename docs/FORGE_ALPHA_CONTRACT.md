# Forge Alpha Contract

## Identity and trust boundary

Forge Alpha is a local control layer with an explicit ownership split. Python is authoritative for lifecycle, review, memory, task-owned MCP result retrieval, and telemetry. The OpenCode TypeScript plugin is authoritative for host-tool policy, native host permission escalation, duplicate-read detection, and host-output compaction. It does not spawn or call Python for each host tool invocation. This is a selective rewrite of `~/Forge`, not an exact copy of its plugin lifecycle enforcement or MCP shell policy.

## Public MCP surface

Exactly five tools are public: `forge_start_task`, `forge_review_changes`, `forge_finish_task`, `forge_submit_outcome`, and `forge_expand_tool_result`. `forge_prepare_context` is removed, not deprecated; start is the sole preparation entry point. Begin-task aliases, memory administration, plugin protocol operations, and Anvil operations are not public.

Every response includes `schema_version`, `ok`, `task_id`, `state`, `warnings`, and `required_next_action`.

## Lifecycle

Persisted states are `active`, `review_blocked`, `reviewed`, `completed`, `failed`, and `degraded`. Review accepts active or nonterminal review states. A passing review records the current observed change digest. Successful finish requires reviewed state and the same current digest. Failed finish is accepted from any nonterminal normal state. Terminal calls are idempotent and do not emit duplicate terminal events. Degraded fallback is unverified, lifecycle-incomplete, and cannot become normally completed.

Agent-reported validation remains reported. Review observes Git state, scope, readable content, and Python syntax only; it makes no semantic correctness claim. Failure is explicit and unsupported behavior is never presented as success.

Lifecycle enforcement is owned by the Python service responses, not by an automatic plugin task state machine. The OpenCode plugin does not create a task, inject a mandatory lifecycle prompt, or reject every mutation performed without a bound task. Agents and integrations must call the public lifecycle tools explicitly.

## Storage and context

Runtime data lives under `~/.forge-alpha/` unless explicitly overridden and never in the controlled repository. The governor has off, report, and active modes. Duplicate reads are tracked per host session. Dangerous commands and cross-repository access escalate through OpenCode's native permission system rather than being converted into permanent plugin errors. The plugin preserves an existing host `deny`, installs `ask` rules for its dangerous-command set, and does not copy the old Forge MCP command allowlist into host-tool policy.

Large host-tool outputs above 8,000 characters are redacted and stored in full by the TypeScript plugin. The model-visible replacement contains at most 20 deterministic summaries labeled with exact original line ranges. `forge_expand_output` supports line retrieval of at most 240 lines and 64,000 content characters per call. Search returns at most 20 matches, accepts 0 to 10 context lines, and uses the same 64,000-character content cap. Both modes are session-owned and have no cumulative expansion quota.

`forge_expand_tool_result` is a separate MCP storage API for task-owned `fr_` handles. It allows at most 16,000 characters per call and 32,000 characters cumulatively per handle. The normal production OpenCode plugin creates `fo_` handles instead, so no standard production flow currently produces an `fr_` handle for this MCP endpoint. The endpoint remains in the five-tool contract as a compatibility surface.

Memory consists only of manually maintained, deterministic JSONL cards. Outcomes never create, modify, promote, or score cards. Anvil is optional guidance elected by agents and has no enforcement or lifecycle effect.

## Non-goals

No embeddings, semantic graph, learning loop, retry controller, autonomous orchestration, Goal Mode, benchmark product, process virtualization, container management, semantic correctness verification, or enforced Anvil is included.

Stored host outputs currently have no TTL or garbage collector. Expansion and search load the stored output into memory before selecting the requested content; this is acceptable for the alpha target but is not a streaming implementation.
