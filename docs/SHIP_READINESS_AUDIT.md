# Forge Ship-Readiness Audit

Date: 2026-06-21

- Old Forge baseline: clean source status; archive branch and annotated tag resolve to `7209fe41e757aa5a3c8fca5ef366ac7d5473e498`; complete bundle and SHA-256 manifest verified.
- Python: 46 tests passed; compileall passed; live-store cross-process freshness and compaction locking passed.
- Packaging: sdist and wheel built; clean Python 3.12 wheel install passed; CLI help and package version passed.
- Runtime smoke: start, observed Git change, reported validation, review, fresh successful finish, and separate degraded fallback passed.
- MCP: discovery returned exactly five contracted public tools.
- Plugin: strict TypeScript check, 15 executable tests, and bundled build passed. The production bundle exposes one v1 plugin module.
- Runtime escalation: OpenCode 1.17.9 evaluated destructive `rm *` as `ask`, emitted a permission request, and rejected execution when approval was unavailable. Cross-repository `/tmp/*` access likewise emitted the native `external_directory` permission request.
- Runtime compaction: a 2,000-line command was reduced to 20 exact line-range summaries; the agent called `forge_expand_output` for lines 995-1005 and recovered original line 1000 correctly. A regression test verifies that search expansion cannot bypass the 64,000-character cap through an oversized matching line.
- Process model: resolved OpenCode configuration contains one plugin entry and one connected MCP registration. The plugin performs no per-call Python IPC.
- Distribution: the rebuilt wheel contains TypeScript sources and bundled `dist/index.js` plugin.
- Source audit: legacy preparation entry points and forbidden subsystems absent from implementation; largest Python module is below 500 lines.
- Independence: installed-wheel smoke used only the new distribution and a temporary home and repository.
- Policy comparison: Alpha preserves the host-native permission and output-virtualization direction from old Forge, but intentionally omits its plugin task state machine and does not copy the MCP shell allowlist into OpenCode built-in tool policy.
- Known debt: `forge_expand_tool_result` remains public although the normal production plugin produces only `forge_expand_output` handles. Host result files also have no TTL or garbage collector and are loaded fully during expansion.

VERDICT: APPROVE WITH DOCUMENTED ALPHA LIMITATIONS
