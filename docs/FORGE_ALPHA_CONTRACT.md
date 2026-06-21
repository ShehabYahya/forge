# Forge Alpha Contract

## Identity and trust boundary

Forge Alpha is a local control layer. Python is authoritative for lifecycle, review, memory, governor, result expansion, and telemetry decisions. Plugins normalize and forward host events and apply Python responses without reinterpretation.

## Public MCP surface

Exactly five tools are public: `forge_start_task`, `forge_review_changes`, `forge_finish_task`, `forge_submit_outcome`, and `forge_expand_tool_result`. `forge_prepare_context` is removed, not deprecated; start is the sole preparation entry point. Begin-task aliases, memory administration, plugin protocol operations, and Anvil operations are not public.

Every response includes `schema_version`, `ok`, `task_id`, `state`, `warnings`, and `required_next_action`.

## Lifecycle

Persisted states are `active`, `review_blocked`, `reviewed`, `completed`, `failed`, and `degraded`. Review accepts active or nonterminal review states. A passing review records the current observed change digest. Successful finish requires reviewed state and the same current digest. Failed finish is accepted from any nonterminal normal state. Terminal calls are idempotent and do not emit duplicate terminal events. Degraded fallback is unverified, lifecycle-incomplete, and cannot become normally completed.

Agent-reported validation remains reported. Review observes Git state, scope, readable content, and Python syntax only; it makes no semantic correctness claim. Failure is explicit and unsupported behavior is never presented as success.

## Storage and context

Runtime data lives under `~/.forge-alpha/` unless explicitly overridden and never in the controlled repository. The governor has off, report, and active modes. Active decisions are enforceable only when an adapter declares the required hook; otherwise they are downgraded with a capability limitation.

Memory consists only of manually maintained, deterministic JSONL cards. Outcomes never create, modify, promote, or score cards. Anvil is optional guidance elected by agents and has no enforcement or lifecycle effect.

## Non-goals

No embeddings, semantic graph, learning loop, retry controller, autonomous orchestration, Goal Mode, benchmark product, process virtualization, container management, semantic correctness verification, or enforced Anvil is included.

