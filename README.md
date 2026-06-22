# Forge Alpha

Forge Alpha is a narrow runtime control layer for coding agents. Python owns task lifecycle, deterministic Git review, local memory selection, telemetry, and memory-maintenance decisions. The OpenCode TypeScript plugin owns host-tool policy, native permission escalation, line-addressable output compaction, and a thin bridge for `/review-memory`. It ports selected concepts from `~/Forge`; it is not a behaviorally identical copy of the old plugin or its MCP shell allowlist.

The normal lifecycle is `forge_start_task` → work → `forge_review_changes` → `forge_finish_task`. Successful completion requires a passing review whose digest still matches the repository. `forge_submit_outcome` is a visibly degraded, unverified fallback. The plugin does not automatically start tasks or block every mutation until a task exists; callers must invoke the lifecycle tools explicitly.

## Install

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
forge-alpha --help
```

Runtime state defaults to `~/.forge-alpha/` and can be redirected through `ForgeService(runtime_root=...)`. Runtime state is never written to a controlled repository.

Memory is no longer manual-only. `forge_finish_task` can create a card from an explicit `memory_draft`, injected cards can receive finish-time `memory_feedback`, and `/review-memory` maintains the active/archived set through the hidden maintenance backend. The registered OpenCode plugin installs that slash command through its config hook; no repo-local command file is required.

The OpenCode plugin preserves full large outputs under that runtime root while showing at most 20 exact source-line summaries. Outputs above 8,000 characters are compacted. Agents retrieve relevant ranges through `forge_expand_output`, with a per-call limit of 240 lines and 64,000 content characters. Search returns at most 20 matches with 0 to 10 context lines and shares the 64,000-character cap. There is no cumulative expansion quota.

The public MCP tool `forge_expand_tool_result` is a separate Python, task-owned result API with a 16,000-character per-call limit and a 32,000-character per-handle budget. The normal production plugin does not currently create its `fr_` handles; host output uses the TypeScript `forge_expand_output` path instead.

Limits: Forge Alpha does not execute tools, sandbox processes, claim semantic correctness, learn from outcomes, or enforce the optional Anvil skill. See [the contract](docs/FORGE_ALPHA_CONTRACT.md) and [installation guide](INSTALL.md).
