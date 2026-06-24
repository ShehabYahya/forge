# Contributing to Forge

Forge is a narrow runtime control layer for coding agents. Contributions that
keep it **narrow, deterministic, and honest** are welcome. This guide covers
setup, the test commands that must pass, the two language stacks, and the
conventions every change is expected to follow.

## Quick start

Python 3.12+ and Node 22 are required for full development.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q          # 334 tests
```

Plugin development (TypeScript):

```bash
cd forge/plugin/opencode
npm install
npm run typecheck && npm test && npm run build
```

## Commands that must pass before a pull request

| Check | Command | What it guards |
|---|---|---|
| Python tests | `python -m pytest -q` | Lifecycle, review, memory, distribution, contracts |
| Documentation tests | `python -m pytest tests/test_documentation.py -q` | Public tool set + link integrity |
| System prompt freshness | `python scripts/generate_forge_system.py --check` | `forge-system.ts` matches its source doc |
| TypeScript types | `npm run typecheck` (in `forge/plugin/opencode`) | Plugin type safety |
| Plugin tests | `npm test` (in `forge/plugin/opencode`) | Governor, compaction, plugin behavior |
| Plugin build | `npm run build` (in `forge/plugin/opencode`) | Bundled `dist/index.js` |
| Version consistency | CI `version-check` job | `forge.__version__` == `package.json` version |

CI runs all of the above on every push to `main` and on pull requests. Run them
locally first.

## The two stacks

- **Python** (`forge/`) is authoritative for lifecycle, review, memory,
  telemetry, and memory-maintenance decisions. It exposes a five-tool MCP stdio
  server and a maintenance bridge.
- **TypeScript** (`forge/plugin/opencode/`) is the OpenCode host plugin. It owns
  host-tool policy (Context Governor), output compaction, system-prompt
  injection, the `/review-memory` command, and MCP/bridge proxying.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the ownership split and
data flow.

## The system prompt is generated

`forge/plugin/opencode/src/forge-system.ts` is **auto-generated** from
`docs/Forge Native Operating.md` by `scripts/generate_forge_system.py`.

- To change the operating protocol, edit `docs/Forge Native Operating.md`, then
  run `python scripts/generate_forge_system.py` to regenerate the TypeScript.
- Never hand-edit `forge-system.ts`. The `--check` CI job will fail if it is
  stale.

## Conventions

- **Honesty over success.** Review observes Git state, scope, readable content,
  and Python syntax only. Never present unsupported behavior as success.
  Agent-reported evidence stays *reported*, never *verified*.
- **No new public tools.** The public MCP surface is exactly five tools. Adding
  a sixth requires changing the contract and `tests/test_mcp_contract.py`.
- **Runtime state stays out of repos.** Write under `~/.forge/` (or a redirected
  root) and never into a controlled repository.
- **No removed systems.** Do not reintroduce embeddings, a semantic graph, a
  learning loop, retries, autonomous orchestration, Goal Mode, or the old MCP
  shell allowlist. The contract's non-goals list is authoritative.
- **Frozen config dataclasses.** Configuration uses frozen, slotted dataclasses
  with spec defaults; on-disk JSON overrides a subset. Keep new settings in the
  same shape and add a test in `tests/test_config.py`.
- **Deterministic memory.** Cards are deterministic JSON/JSONL. The backend owns
  IDs, metadata, and writes; nothing edits memory JSON directly.

## Tests as behavior specs

Tests double as the behavioral spec. When you change behavior, update the
corresponding test:

- Lifecycle transitions → `tests/test_lifecycle.py`
- Review verdicts and evidence → `tests/test_review_verdict.py`, `test_review_diff.py`
- Public tool contract → `tests/test_mcp_contract.py`, `test_service_contract.py`
- Memory cards and scoring → `tests/test_memory_*.py`
- Distribution install/doctor → `tests/test_distribution.py`, `test_release_*.py`

## Commit and pull request style

- Use concise imperative commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`)
  matching the existing history.
- Keep pull requests focused. Large multi-concern changes are hard to review
  deterministically.
- If a change affects the public tool surface, the contract, or the operating
  prompt, call it out explicitly in the PR description.
- Bump `forge.__version__` **and** `forge/plugin/opencode/package.json` together;
  they must always match (enforced by CI).

## Reporting issues

Use the issue templates in `.github/ISSUE_TEMPLATE/`. Include the output of
`forge doctor` for installation or runtime problems.
