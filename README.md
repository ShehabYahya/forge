# Forge

**A narrow runtime control layer for coding agents.**

Forge gives an agent host a deterministic task lifecycle, an honest review gate
before work is marked done, local memory selection, telemetry, and safe output
compaction. It does **not** run agents, execute tools, sandbox processes, or
claim semantic correctness — it makes agent work *auditable* and *honest* about
what was actually verified.

> Forge is in alpha (`0.1.0-alpha.1`). Breaking changes may occur before `1.0`.

## Why

Coding agents routinely declare success without anyone checking what changed.
Forge attaches a cheap, deterministic checkpoint to every substantive task:
capture a baseline, do the work, review the real Git delta, and only then allow
a verified finish. The review observes Git state, scope, readable content, and
Python syntax — never a semantic-correctness claim — so "done" always means
something specific and checkable.

## The lifecycle

```
forge_start_task  →  work  →  forge_review_changes  →  forge_finish_task
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
curl -fsSL https://github.com/username/forge/releases/latest/download/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://github.com/username/forge/releases/latest/download/install.ps1 | iex
```

Pin a version with `FORGE_VERSION=0.1.0-alpha.1`. The installer verifies every
download against its published SHA-256 checksum, then runs `forge doctor`.

> Replace `username` with the published GitHub owner before tagging a release.

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

## What Forge does and does not do

**Does:** deterministic lifecycle, honest Git review, local memory cards,
append-only telemetry, host-output compaction, host-native permission
escalation for dangerous commands.

**Does not:** execute tools, sandbox processes, verify semantic correctness,
learn from outcomes, run autonomously, or manage containers.

See the [contract](docs/FORGE_CONTRACT.md) for the authoritative behavioral
boundaries and the [non-goals](docs/FORGE_CONTRACT.md#non-goals) list.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — the Python/TypeScript ownership split
  and data flow
- [Contract](docs/FORGE_CONTRACT.md) — public surface, lifecycle, storage
- [Lifecycle](docs/LIFECYCLE.md) — states, baseline trees, review fields
- [Memory](docs/MEMORY.md) — cards, injection, feedback, maintenance
- [Context Governor](docs/CONTEXT_GOVERNOR.md) — host-tool policy and compaction
- [Walkthrough](docs/WALKTHROUGH.md) — a complete end-to-end run
- [Troubleshooting](docs/TROUBLESHOOTING.md) — common problems and fixes
- [Ship-readiness audit](docs/SHIP_READINESS_AUDIT.md) — alpha verification record

## Project

- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)
- [License](LICENSE) (MIT)

## Status

Alpha. The codebase has 334 passing Python tests, a TypeScript plugin test
suite, CI for tests/types/docs/version consistency, and a multi-platform
release workflow with per-target smoke tests. Known alpha debt — no TTL on
stored outputs, and the `forge_expand_tool_result` compatibility surface — is
documented in the [contract](docs/FORGE_CONTRACT.md).
