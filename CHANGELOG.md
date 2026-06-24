# Changelog

All notable changes to Forge are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) within the
`0.x` alpha series (breaking changes may occur before `1.0`).

Versions in `forge.__version__` and `forge/plugin/opencode/package.json` are kept
identical and enforced by CI.

## [0.1.0-alpha.1] — 2026-06-21

First public alpha. Forge ships as a narrow runtime control layer for coding
agents with a deterministic lifecycle, honest Git review, local memory, and an
OpenCode host plugin.

### Added
- Five-tool public MCP surface: `forge_start_task`, `forge_review_changes`,
  `forge_finish_task`, `forge_submit_outcome`, `forge_expand_tool_result`.
- Deterministic lifecycle state machine: `active`, `review_blocked`,
  `reviewed`, `completed`, `failed`, `degraded`.
- Baseline-tree capture at task start using a temporary Git index; task-delta
  isolation from pre-existing dirty files at review.
- Honest review observing Git state, scope, readable content, and Python syntax
  only; agent-reported validation recorded as reported, never as verified.
- Deterministic memory cards under `~/.forge/memory/` with opt-in finish-time
  creation, injected-card feedback, and `/review-memory` maintenance.
- OpenCode TypeScript plugin: Context Governor (host-native policy), output
  compaction with `fo_` handles and exact line-range summaries, deduplicated
  system-prompt injection, and `/review-memory` command registration.
- Global distribution: `forge install`, `forge doctor`, `forge uninstall`,
  `forge purge`; SHA-256-verified release bundles for Linux, macOS, and Windows.
- CI for Python tests, plugin tests, type checking, documentation contracts,
  version consistency, and a release workflow with per-target smoke tests.

### Known limitations
- Stored host outputs have no TTL or garbage collector and are loaded fully into
  memory during expansion.
- `forge_expand_tool_result` (`fr_` handles) remains public as a compatibility
  surface; the normal production plugin produces only `forge_expand_output`
  (`fo_`) handles.
- Alpha-stage: breaking changes may occur before `1.0`.

[0.1.0-alpha.1]: https://github.com/anomalyco/forge/releases/tag/v0.1.0-alpha.1
