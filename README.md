# Forge

**The proof layer for coding agents.**

Forge gives AI coding work a real delivery pipeline: scope the task, pull in
the right memory, make the change, validate it, run an independent review loop,
inspect the real Git delta, and seal the result with a finish receipt.

Agents move fast. Forge makes them leave evidence.

> Forge is alpha infra (`0.1.0-alpha.1`). The core workflow is intentionally
> usable now, while public install and integration details may change before
> `1.0`.

## Why

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

Forge is a proof and workflow layer, not a sandbox or test runner. It does not
execute tools, manage containers, or claim semantic correctness. It records and
checks the evidence that a coding agent leaves behind.

The exact behavioral contract is in [FORGE_CONTRACT.md](docs/FORGE_CONTRACT.md).

## Documentation

- [Why Forge](docs/WHY_FORGE.md) — product case and research-backed workflow claims
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
