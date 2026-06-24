# Forge

**Agents say done. Forge shows proof.**

Forge is the proof layer for coding agents. It turns AI coding work into an
inspectable receipt: what changed, what stayed in scope, what validation was
observed, whether review was fresh, what uncertainty remains, and what should be
remembered next time.

Your coding agent still writes the code. Forge makes the work leave evidence.

> Forge is alpha infra (`0.1.0-alpha.1`). The core workflow is intentionally
> usable now, while public install and integration details may change before
> `1.0`.

## What Forge Catches

Forge is built for the failures that hide behind a polished final paragraph:

- The agent says tests passed, but no passing validation was observed.
- Review happened before the final edit, so the review is stale.
- Files changed outside the declared task boundary.
- A failed command was reframed as success.
- A useful repo lesson was lost instead of becoming local memory.
- A large output was compressed without a way to inspect exact lines later.

Forge does not make agents magically correct. It makes correctness claims harder
to fake.

## Receipt First

Every serious task should end with something more useful than "done":

```text
Forge Receipt

Task: Fix config loading bug
Outcome: completed, validation observed

Changed files:
- forge/config.py
- tests/test_config.py

Scope:
- Declared: forge/config.py, tests/test_config.py
- Extra files: none
- Review freshness: fresh after final edit

Validation:
- pytest tests/test_config.py -q: observed passed
- Ran after last edit: yes

Review:
- Git delta: inspected
- Scope: passed
- Syntax: passed
- Remaining uncertainty: not tested on Windows

Memory:
- 1 candidate lesson recorded for future tasks
```

`forge_review_changes` issues the draft proof: real Git delta, scope, syntax,
validation evidence, and staleness. `forge_finish_task` seals the receipt only
when the review is fresh enough to support the result.

## Why Forge

Modern coding agents can ship useful work, but they also drift scope, overstate
validation, miss their own mistakes, and take risky actions with too much
confidence. Forge is the harness around that behavior: an AI-native workflow
that turns "the agent says it is done" into a concrete receipt of what happened.

Forge is built for the gap between raw agent autonomy and production discipline:

- **Structured workflow:** tasks move through start, scoped work, validation,
  review, and finish instead of ending in an unverified final message.
- **Scope accuracy:** Forge captures a baseline and compares the actual task
  delta against the declared file boundary.
- **Independent review:** nontrivial work goes through a system-prompted
  plan-review and implementation-review loop before completion.
- **Safety friction:** destructive command patterns and cross-repository access
  are escalated through host-native permission controls.
- **Finish receipts:** every completed task records changed files, review
  status, validation evidence, remaining uncertainty, and memory candidates.
- **Memory hygiene:** useful lessons become local memory cards; stale or noisy
  cards are maintained through `/review-memory`.

## Who This Alpha Is For

Forge is useful today if you delegate real repository changes to agents and want
auditability around scope, validation, review freshness, and memory. It is aimed
at agent-heavy builders, tool authors, and teams evaluating higher-autonomy
coding workflows.

Forge is probably too much process for tiny one-off edits, pure Q&A, or users
expecting a full sandbox, CI system, or semantic correctness oracle.

## Not Another Coding Agent

Forge does not compete with coding agents. It wraps them.

Use Codex, Claude Code, Copilot, OpenCode, or another agent to do the work.
Forge's job is to make the work inspectable: start from a scope, preserve the
task boundary, check the real Git delta, observe validation evidence when
available, block stale successful finishes, and record the final receipt.

## Workflow

```mermaid
flowchart TD
    A[User task] --> B[Forge system prompt<br/>operating protocol]
    B --> C[forge_start_task<br/>scope + baseline + memory brief]
    C --> D[Relevant memory cards<br/>injected into context]
    D --> E[Plan]
    E --> F{Independent plan review<br/>subagent loop}
    F -- blockers --> E
    F -- pass --> G[Implementation]
    G --> H[Validation evidence<br/>tests, checks, reasoning]
    H --> I{Independent implementation review<br/>subagent loop}
    I -- issues --> G
    I -- pass --> J[forge_review_changes<br/>Git delta + scope + syntax + digest]
    J -- blocked or stale --> G
    J -- pass --> K[forge_finish_task<br/>finish receipt]
    K --> L[Memory draft + feedback]
    L --> M[(~/.forge/memory)]
    M --> N[/review-memory<br/>edit, archive, merge, backfill]
    N --> M
```

The Independent Review Loop is qualitative and agent-driven: a separate
read-only context reviews the plan before implementation and the patch after
implementation. `forge_review_changes` is mechanical and runtime-owned: it
checks the real task delta, scope, syntax, and review digest. The two gates are
different on purpose.

## Finish Receipts

A Forge finish receipt is the artifact you can trust more than an agent's final
paragraph. It answers:

- What task was started?
- Which files actually changed?
- Did the work stay inside declared scope?
- Was the task reviewed after the final edit?
- What validation was reported or observed?
- What uncertainty remains?
- What should be remembered next time?

Forge makes correctness claims harder to fake. It turns the agent's workflow
into evidence you can inspect instead of prose you have to trust.

## Lifecycle

```
forge_start_task -> work -> forge_review_changes -> forge_finish_task
```

- **Start** captures a baseline tree of the worktree and returns prepared
  context plus a memory brief.
- **Review** compares the current worktree against the baseline, isolates the
  task delta from pre-existing dirty files, runs scope and syntax checks, and
  records a digest.
- **Finish** succeeds only when the task is reviewed **and** the worktree digest
  is unchanged. Any edit after review makes that review stale.
- **Degraded** (`forge_submit_outcome`) is a visibly *unverified* fallback for
  when normal completion is impossible — never a shortcut to "done".

## Install

### Global install (recommended)

Installs a self-contained runtime — no Python, npm, or source checkout needed.
Forge integrates globally into OpenCode and writes nothing into your
repositories.

**Linux / macOS:**

```bash
curl -fsSL https://github.com/anomalyco/forge/releases/latest/download/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://github.com/anomalyco/forge/releases/latest/download/install.ps1 | iex
```

Pin a specific version with `FORGE_VERSION` (e.g. `FORGE_VERSION=0.1.0-alpha.1`).
The installer verifies every download against its published SHA-256 checksum,
extracts the self-contained bundle, and delegates to `forge install`, which
atomically activates the version and runs diagnostics.

### From source (contributors)

Requires Python 3.12+.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
forge --help
```

See [INSTALL.md](INSTALL.md) for the full guide and
[CONTRIBUTING.md](CONTRIBUTING.md) for development setup.

## Commands

| Command | Purpose |
|---|---|
| `forge install` | Install Forge globally into OpenCode |
| `forge doctor` | Verify installation integrity |
| `forge uninstall` | Remove Forge integration (preserves runtime data) |
| `forge purge` | Remove runtime data at `~/.forge/` |
| `forge mcp` | Start the MCP stdio server |
| `forge bridge` | Start the maintenance bridge on stdin/stdout |
| `forge version` | Print the version |

Runtime state defaults to `~/.forge/` and can be redirected with `FORGE_HOME`
(or legacy `FORGE_ALPHA_HOME`). It is never written to a controlled repository.

## What Forge Adds

| Capability | What it gives the agent workflow |
|---|---|
| Scoped task lifecycle | A clear beginning, declared boundary, and terminal outcome |
| Baseline-backed review | Real Git delta inspection instead of trusting the final message |
| Independent Review Loop | Separate plan and implementation critique for nontrivial work |
| Stale-review blocking | Any edit after review requires another review before success |
| Host-native safety friction | Destructive and out-of-repo actions escalate through the host |
| Local memory cards | Reusable lessons are injected at the next relevant task |
| `/review-memory` | A maintenance lane for pruning, merging, restoring, and backfilling memory |
| Output compaction | Large outputs become exact, expandable line-range handles |

## Boundaries

Forge can prove workflow facts: what files changed, whether the declared scope
was respected, whether review is fresh, whether validation was reported or
observed, and what evidence was attached to the final receipt.

Forge cannot prove full semantic correctness. It is not a sandbox, container
manager, test runner, or replacement for human judgment. Unsupported behavior is
recorded as unsupported, not presented as success.

The exact behavioral contract is in [FORGE_CONTRACT.md](docs/FORGE_CONTRACT.md).

## Documentation

- [Why Forge](docs/WHY_FORGE.md) — product case and research-backed workflow claims
- [Receipts](docs/RECEIPTS.md) — what Forge records when agent work finishes
- [Architecture](docs/ARCHITECTURE.md) — the Python/TypeScript ownership split
  and data flow
- [Contract](docs/FORGE_CONTRACT.md) — public surface, lifecycle, storage
- [Lifecycle](docs/LIFECYCLE.md) — states, baseline trees, review fields
- [Memory](docs/MEMORY.md) — cards, injection, feedback, maintenance
- [Context Governor](docs/CONTEXT_GOVERNOR.md) — host-tool policy and compaction
- [Walkthrough](docs/WALKTHROUGH.md) — a complete end-to-end run
- [Troubleshooting](docs/TROUBLESHOOTING.md) — common problems and fixes

## Project

- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)
- [License](LICENSE) (MIT)

## Status

Alpha. Forge is for builders who want agent speed without losing auditability,
scope discipline, review pressure, and local memory hygiene. Exact guarantees
are documented in the [contract](docs/FORGE_CONTRACT.md).
