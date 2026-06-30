# Context Governor

The OpenCode governor runs in-process in TypeScript and does not start a Python process per tool call. Modes are `off`, `report`, and `active`; decisions are allow, warn, escalate, and block. It uses the same host-native policy direction as `~/Forge`, but it is a rewrite rather than a policy-identical port.

Exact duplicate reads are tracked per OpenCode session. Dangerous commands return `escalate`; the plugin configures native OpenCode `ask` rules for `rm`, privileged or system commands, high-impact filesystem commands, and destructive Git commands. Existing `deny` rules are never weakened. Cross-repository operations are delegated to OpenCode's built-in `external_directory` permission prompt. Escalation is never implemented by throwing a retry error.

This policy is deliberately not the old Forge MCP shell allowlist. It does not enforce task creation before every mutation, and commands such as ordinary package installs or network reads are left to the host's configured policy unless they match an existing host rule. Python lifecycle and MCP policy remain separate from built-in host-tool permissions.

`/review-memory` is the explicit maintenance exception path. While memory review mode is active, the plugin refreshes the backend-provided allowlist and denies every tool not on it. Allowed maintenance calls bypass lifecycle assumptions and Context Governor decisions until the mode finishes.

## See also

- [Contract](FORGE_CONTRACT.md) — the authoritative behavioral contract
- [Memory](MEMORY.md) — the `/review-memory` maintenance exception
