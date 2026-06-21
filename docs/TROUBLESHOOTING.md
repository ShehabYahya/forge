# Troubleshooting

- Corrupt JSONL: valid later task or card records still load; warnings identify skipped lines.
- Stale review: rerun review after the final edit, then finish.
- Backend outage: the plugin reports degraded adapter status and makes no enforcement claim.
- `forge_expand_output` error: use the `fo_` handle from the same OpenCode session. A range may contain at most 240 lines and 64,000 content characters; search allows at most 10 context lines, returns at most 20 matches, and shares the character cap. There is no cumulative quota.
- `forge_expand_tool_result` error: this separate MCP endpoint requires a task-owned `fr_` handle, allows at most 16,000 characters per call, and has a 32,000-character cumulative handle budget. The normal production plugin does not currently generate these handles.
