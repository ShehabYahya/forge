# Troubleshooting

## Installation

- **Checksum verification fails:** Re-download the installation script. If the issue persists, the release may have been corrupted. Check the SHA-256 checksum against the published release manifest.

- **Installation rollback:** A failed installation leaves the previous version active. Run `forge doctor` to verify the current state, then retry installation.

- **Plugin not discovered:** Run `forge doctor`. If the global loader is missing, reinstall. Verify your OpenCode config root is correctly detected (override with `--config-root` or `OPENCODE_CONFIG_DIR`).

- **MCP not connecting:** Ensure the native executable is present and executable. Run `forge doctor` to check executable startup. The plugin config hook registers the MCP process automatically; do not add a duplicate manual MCP registration.

- **Forge tools not appearing:** OpenCode must start a new session after installation. The Forge MCP is discovered at session start.

- **Old `forge-alpha_forge_*` tool names appear:** restart OpenCode and remove stale manual MCP registrations. The plugin registers MCP key `forge`, so the public tools should appear as `forge_start_task`, `forge_review_changes`, `forge_finish_task`, `forge_submit_outcome`, and `forge_expand_tool_result`.

## Runtime

- **Corrupt JSONL:** valid later task or card records still load; warnings identify skipped lines.
- **Stale review:** rerun review after the final edit, then finish.
- **Backend outage:** the plugin reports degraded adapter status and makes no enforcement claim.
- **`forge_expand_output` error:** use the `fo_` handle from the same OpenCode session. A range may contain at most 240 lines and 64,000 content characters; search allows at most 10 context lines, returns at most 20 matches, and shares the character cap. There is no cumulative quota.
- **`forge_expand_tool_result` error:** this separate MCP endpoint requires a task-owned `fr_` handle, allows at most 16,000 characters per call, and has a 32,000-character cumulative handle budget. The normal production plugin does not currently generate these handles.

## Getting help

1. Run `forge doctor` first — it identifies the most common installation
   problems and exits non-zero on failure.
2. Check the release manifest at your installed version directory.
3. Review [Architecture](ARCHITECTURE.md) and the
   [Contract](FORGE_CONTRACT.md) to confirm expected behavior.
4. If the issue persists, open an issue using the bug report template in
   `.github/ISSUE_TEMPLATE/` and attach the `forge doctor` output. Do not
   include secrets.
