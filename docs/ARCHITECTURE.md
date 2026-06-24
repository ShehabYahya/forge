# Architecture

Forge is a **narrow runtime control layer for coding agents**. It does not run
agents, execute tools, or verify semantic correctness. It gives an agent host a
deterministic lifecycle, an honest review gate, local memory selection,
telemetry, and safe output compaction.

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
        │   forge/review/           Git baseline + delta + verdict       │
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

- A successful finish requires `reviewed` **and** an unchanged total-worktree
  digest. Any edit after review — even to a file the task never touched — makes
  the review stale.
- At `start_task`, Forge captures a **baseline tree** using a temporary Git
  index (the user's real index is never touched). Review compares the current
  worktree against that baseline to isolate the **task delta** from pre-existing
  dirty files.
- `degraded` is a visibly unverified fallback. It can never be upgraded to
  `completed`.

## Public surface

Exactly five MCP tools are public (server key `forge`):

| Tool | Purpose |
|---|---|
| `forge_start_task` | Begin a scoped task; return prepared context + memory brief |
| `forge_review_changes` | Observe the Git delta, run scope/syntax checks, record a digest |
| `forge_finish_task` | Terminal completion requiring a fresh passing review |
| `forge_submit_outcome` | Degraded, unverified fallback only |
| `forge_expand_tool_result` | Expand task-owned `fr_` result handles (compatibility surface) |

`forge_expand_output` is a **host-side** compaction tool exposed by the
TypeScript plugin, not by the Python MCP server. It works on session-owned `fo_`
handles. The two expansion APIs are intentionally distinct.

## Review model

Forge review observes **Git state, scope, readable content, and Python syntax
only**. It makes no semantic-correctness claim. Agent-reported validation
evidence is recorded as *reported*, never promoted to a verified claim. Failure
is explicit; unsupported behavior is never presented as success.

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
- [Lifecycle](LIFECYCLE.md) — states, baseline trees, review fields
- [Memory](MEMORY.md) — cards, injection, feedback, maintenance
- [Context Governor](CONTEXT_GOVERNOR.md) — host-tool policy and compaction
- [Walkthrough](WALKTHROUGH.md) — a complete end-to-end run
