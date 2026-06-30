# Architecture

Forge is the **proof layer for coding agents**. It wraps an agent host with a
structured delivery pipeline: task scope, local memory injection, validation
evidence, independent review pressure, session-log review, finish receipts, and
safe output compaction.

The system has two cooperating halves with a strict ownership split.

```
        ┌─────────────────────────────────────────────────────────────┐
        │                      Agent host (OpenCode)                   │
        │                                                               │
        │   model ──► Forge system prompt (operating protocol)          │
        │            │                                                  │
        │            ▼                                                  │
        │   forge_start_task ── forge_review_changes ── forge_finish_task
        │            │                  │                   │           │
        │            ▼                  ▼                   ▼           │
        │   ┌──────────────────────────────────────────────────────┐   │
        │   │  TypeScript plugin (host-native, in-process)         │   │
        │   │  • Context Governor (read/danger/scope policy)       │   │
        │   │  • Output compaction (fo_ handles, line summaries)   │   │
        │   │  • System-prompt injection (deduplicated)            │   │
        │   │  • /review-memory command + maintenance adapter      │   │
        │   │  • MCP lifecycle tool proxying                       │   │
        │   └───────────────┬──────────────────────┬───────────────┘   │
        │                   │ bridge (stdio JSON)  │ MCP (stdio)        │
        └───────────────────┼──────────────────────┼───────────────────┘
                            │                      │
                            ▼                      ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                   Python runtime (authoritative)              │
        │                                                               │
        │   forge/service.py        ForgeService — five public ops      │
        │   forge/lifecycle.py      state machine (active → … → done)   │
        │   forge/review/           Session digest + verdict             │
        │   forge/memory/           deterministic cards, scoring, store │
        │   forge/telemetry/        append-only events + honesty signal │
        │   forge/context/          task-owned result store (fr_)        │
        │   forge/mcp_server.py     FastMCP stdio server (5 tools)      │
        │   forge/plugin/bridge.py  maintenance bridge protocol         │
        │   forge/distribution.py   install / doctor / uninstall        │
        │                                                               │
        │   Runtime state → ~/.forge/  (never inside a controlled repo) │
        └───────────────────────────────────────────────────────────────┘
```

## Workflow loop

Forge combines two kinds of review:

- the **Independent Review Loop**, prompted inside the agent workflow and run
  by a separate read-only context for nontrivial plan and implementation review
- `forge_review_changes`, the runtime-owned mechanical review of session-owned
  changed files, scope, syntax, and staleness digest

```mermaid
flowchart TD
    A[User task] --> B[start_task<br/>scope]
    B --> C[memory brief]
    C --> D[plan]
    D --> E{independent plan review}
    E -- revise --> D
    E -- pass --> F[implementation]
    F --> G[validation evidence]
    G --> H{independent implementation review}
    H -- patch --> F
    H -- pass --> I[review_changes<br/>delta + scope + digest]
    I -- stale or blocked --> F
    I -- pass --> J[finish_task<br/>receipt + memory draft]
    J --> K[(memory cards)]
    K --> L[/review-memory]
    L --> K
```

## Ownership split

| Concern | Owner | Why |
|---|---|---|
| Task lifecycle, review verdict, memory selection, telemetry | Python | Must be deterministic, testable, and host-agnostic |
| Host-tool policy, permission escalation, duplicate-read detection | TypeScript plugin | Must be native to the host and run in-process per call |
| Output compaction of large host tool results | TypeScript plugin | Must intercept host output before it reaches the model |
| Memory-maintenance decisions (edit/archive/merge) | Python | Validation and batching belong with the data |
| Proxying `/review-memory` to the backend | TypeScript plugin | The command lives in the host; the backend owns logic |

The plugin **never** starts a Python process per tool call. Lifecycle calls go
over MCP stdio; maintenance calls go over a single long-lived bridge child
process. This is a deliberate change from the earlier per-call transport model.

## Lifecycle state machine

```
        start_task
   ┌─────────────┐
   │   active    │
   └──────┬──────┘
          │ review_changes
          ├──────────────► review_blocked ──┐
          │                                 │ (resolve blockers, review again)
          ▼                                 │
      reviewed ◄────────────────────────────┘
          │  finish_task(success, digest matches)
          ▼
      completed

   any nonterminal ── finish_task(success=false) ──► failed
   normal impossible ── submit_outcome ──► degraded (unverified, terminal)
```

- A successful finish requires `reviewed` **and** an unchanged session digest.
  Any logged edit after review makes the review stale.
- `start_task` no longer captures a Git baseline. Review relies on the host's
  session digest for task-owned file attribution.
- `degraded` is a visibly unverified fallback. It can never be upgraded to
  `completed`.

## Public surface

Exactly five MCP tools are public (server key `forge`):

| Tool | Purpose |
|---|---|
| `forge_start_task` | Begin a scoped task; return prepared context + memory brief |
| `forge_review_changes` | Observe the session-owned changed files, run scope/syntax checks, record a digest |
| `forge_finish_task` | Terminal completion requiring a fresh passing review |
| `forge_submit_outcome` | Degraded, unverified fallback only |
| `forge_expand_tool_result` | Expand task-owned `fr_` result handles (compatibility surface) |

`forge_expand_output` is a **host-side** compaction tool exposed by the
TypeScript plugin, not by the Python MCP server. It works on session-owned `fo_`
handles. The two expansion APIs are intentionally distinct.

## Review model

Forge review centers on **session-owned changed files, scope, readable content,
Python syntax, and recorded validation evidence**. Its job is not to replace
tests or human judgment; its job is to make the agent's claims inspectable
against host-observed session state. Agent-reported validation evidence is recorded as *reported*
unless the runtime has direct evidence. Failure is explicit; unsupported
behavior is never presented as success.

## Memory model

Memory cards are deterministic JSON/JSONL artifacts under `~/.forge/memory/`.

- **Injection** at `start_task` is deterministic, repo-scoped, bounded to 10
  cards and 4,000 characters.
- **Creation** at `finish_task` is mandatory via an explicit `memory_draft` (except for documented exemptions: mismatch, degraded, or no-lesson-with-explicit-reason);
  invalid or generic drafts are rejected without failing the task.
- **Feedback** at `finish_task` scores only cards that were actually injected.
- **Maintenance** happens through `/review-memory`, backed by the hidden Python
  maintenance service. It runs deny-by-default and bypasses the governor and
  compaction while active.

The backend owns memory IDs, metadata, confidence, validation, storage, and
writes. Nothing edits memory JSON directly.

## Storage layout

```
~/.forge/
├── tasks.jsonl              append-only task snapshots (superseding)
├── telemetry.jsonl          append-only lifecycle events
├── config.json              optional overrides (subset of defaults)
├── memory/
│   ├── memory_cards.json            active cards
│   ├── memory_cards_deleted.json    archived cards
│   ├── memory_feedback.jsonl        finish-time ratings
│   ├── memory_review_log.jsonl      maintenance batch log
│   └── memory_id_counter.json       global card id allocator
└── tool-results/            task-owned redacted outputs (fr_ handles)
```

Runtime state is never written into a controlled repository. `FORGE_HOME` (or
legacy `FORGE_ALPHA_HOME`) redirects the root.

## Non-goals

Forge intentionally does **not** include: embeddings or a semantic graph, a
learning loop, a retry controller, autonomous orchestration, Goal Mode, a
benchmark product, process virtualization, container management, or semantic
correctness verification. Stored host outputs currently have no TTL or garbage
collector and are loaded fully into memory during expansion — acceptable for
alpha, called out as known debt.

## Further reading

- [Contract](FORGE_CONTRACT.md) — the authoritative behavioral contract
- [Receipts](RECEIPTS.md) — what Forge records when agent work finishes
- [Why Forge](WHY_FORGE.md) — the product case and research-backed workflow claims
- [Lifecycle](LIFECYCLE.md) — states, session review fields
- [Memory](MEMORY.md) — cards, injection, feedback, maintenance
- [Context Governor](CONTEXT_GOVERNOR.md) — host-tool policy and compaction
- [Walkthrough](WALKTHROUGH.md) — a complete end-to-end run
