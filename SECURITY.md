# Security Policy

Forge runs locally on your machine and operates on your Git repositories. This
document explains what Forge does and does not do with your code and data.

## Reporting a vulnerability

If you discover a security issue, please **do not** open a public issue. Report
it privately so a fix can be prepared before disclosure. Include:

- A description of the issue and its impact
- Steps to reproduce
- The output of `forge doctor` if relevant

## What Forge touches

- **Your repositories:** Forge observes file changes through the host session
  log — the TypeScript plugin tracks edits and writes per session; review
  inspects the session-owned change ledger instead of Git trees. The lifecycle
  review reads file content and runs `python -m compileall` for syntax checks.
- **Runtime state:** Forge writes under `~/.forge/` by default (redirect with
  `FORGE_HOME`). This includes task snapshots, telemetry, memory cards, and
  redacted tool outputs. **Runtime state is never written into a controlled
  repository.**
- **Configuration:** `forge install` merges Forge entries into your global
  OpenCode configuration. Existing settings and comments are preserved, changes
  are backed up, and a failed install leaves the prior configuration intact.

## Trust boundaries

- Forge **does not execute arbitrary tools on your behalf**, sandbox processes,
  or claim semantic correctness. Review observes Git state, scope, readable
  content, and Python syntax only.
- Dangerous commands (destructive `rm`, privileged/system commands, destructive
  Git commands) escalate through OpenCode's native permission system as `ask`
  rules. Forge never weakens an existing host `deny`.
- Cross-repository access is delegated to OpenCode's built-in
  `external_directory` permission prompt.
- The Context Governor may warn, block, or escalate duplicate reads, dangerous
  commands, and out-of-repo access. It runs automatically; you do not invoke it.
- `/review-memory` maintenance mode runs deny-by-default and bypasses the
  governor and compaction only while explicitly active.

## Secrets

Never include secrets in task text, evidence, summaries, memory drafts, or
delegated prompts. Runtime artifacts under `~/.forge/` are not encrypted at
rest; treat that directory as untrusted and avoid pointing Forge at content that
contains credentials.

## Release integrity

Published release bundles are accompanied by SHA-256 checksums. The installer
verifies every downloaded archive against its published digest before
extraction. If verification fails, installation is refused and the prior
installation remains usable.

## Scope

This policy covers the Forge runtime and the OpenCode plugin shipped from this
repository. It does not cover third-party dependencies, which carry their own
advisories.
