# Forge Production-Readiness Review

Date: 2026-06-27

Method: 33 headless `opencode-go/deepseek-v4-flash` review sessions (2 files max each),
dispatched in 6 waves of 6 concurrent sessions. Each session read `README.md` and
`INSTALL.md` in full, then compared them to its assigned source files. 64 files reviewed
(source + build artifacts + packaging + install scripts; tests excluded). Read-only: no
source files were modified (`git status` clean after review).

All 33 JSON reports: `/tmp/opencode/reviews/S01.json` through `S33.json`.

---

> **Validated 2026-06-27** by a second review swarm (5 × `opencode-go/deepseek-v4-pro` sessions).
> Of 254 findings: **214 confirmed (84.3%)**, **10 refuted (3.9%)**, **30 partial (11.8%)**.
> All 9 blockers confirmed. This document has been updated: refuted findings removed,
> partial findings corrected with updated line numbers, severities, categories, and validation notes.

## Verdict: NOT PRODUCTION-READY

5 of 33 sessions returned a `blocker` verdict; 28 returned `issues`. Zero `pass`.

## Summary

| Metric | Value |
|---|---|
| Files reviewed | 64 |
| Review sessions | 33 (original) + 5 (validation) |
| Total findings | 244 |
| Blocker verdicts | 5 sessions |
| Issue verdicts | 28 sessions |

### Findings by severity

| Severity | Count |
|---|---|
| blocker | 9 |
| high | 28 |
| medium | 74 |
| low | 113 |
| nit | 20 |

### Findings by category

| Category | Count |
|---|---|
| bug | 85 |
| slop | 52 |
| readme_drift | 28 |
| other | 26 |
| duplicate | 20 |
| naming_drift | 16 |
| unsubstantiated_claim | 6 |
| install_accuracy | 2 |

---

## Blocker Findings (9)

These must be fixed before shipping.

### B1. [forge/distribution/install.py:237] _write_global_assets calls shutil.copy2(skill_src, ...) without existence check; crash if SKILL.md missing

- **Session:** S03 (forge/distribution/install.py + forge/distribution/uninstall.py)
- **Category:** bug
- **Evidence:** Line 237: `shutil.copy2(skill_src, skill_dst / "SKILL.md")` — no `if skill_src.exists()` guard, unlike loader_src at line 231 (`if loader_src.exists():`). If SKILL.md is absent from the source tree (e.g., incomplete checkout), this raises FileNotFoundError and crashes the install.
- **Fix:** Add `if skill_src.exists():` guard matching the loader_src pattern, or add it at the top alongside the loader_src check and raise/return early.

### B2. [scripts/install.sh:39] Latest version resolution fetches from an invalid GitHub URL, breaking the default install path

- **Session:** S06 (scripts/build_release.py + scripts/install.sh)
- **Category:** bug
- **Evidence:** VERSION=$(curl -fsSL "${RELEASE_BASE}/latest.txt" 2>/dev/null || echo "") — constructs URL https://github.com/ShehabYahya/forge/releases/download/latest.txt which is not a valid GitHub release asset URL (missing tag component). Every GitHub release download URL must follow /releases/download/<tag>/<asset>.
- **Fix:** Use the GitHub API or /releases/latest endpoint to resolve the latest release tag: e.g. curl -fsSL https://api.github.com/repos/ShehabYahya/forge/releases/latest | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])"

### B3. [scripts/install.sh:61] Uses sha256sum which does not exist on macOS, breaking the only supported non-Linux platform

- **Session:** S06 (scripts/build_release.py + scripts/install.sh)
- **Category:** bug
- **Evidence:** ACTUAL=$(sha256sum "${TMPDIR}/${ARCHIVE}" | cut -d' ' -f1) — macOS ships shasum -a 256, not sha256sum. Script header says 'Linux / macOS' but will fail on macOS.
- **Fix:** Replace with: if command -v sha256sum >/dev/null 2>&1; then SHA_CMD="sha256sum"; else SHA_CMD="shasum -a 256"; fi; ACTUAL=$($SHA_CMD ...)

### B4. [forge/plugin/session_state.py:3] fcntl import makes code Unix-only, contradicting documented Windows support

- **Session:** S10 (forge/task_state.py + forge/plugin/session_state.py)
- **Category:** install_accuracy
- **Evidence:** Line 3: `import fcntl`. INSTALL.md line 18: `irm https://github.com/ShehabYahya/forge/releases/latest/download/install.ps1 | iex`. README.md lines 183-187 advertise Windows PowerShell install. fcntl does not exist on Windows; this import will raise ModuleNotFoundError. The same blocker exists in at least 7 other forge modules (persistence.py, memory/store.py, memory/feedback_store.py, memory/review_log.py, telemetry/writer.py, context/result_store.py, migrate_tasks.py).
- **Fix:** Replace fcntl with cross-platform file locking: either use a conditional import (fcntl on Unix, msvcrt or portalocker on Windows) or add a cross-platform abstraction layer (e.g. forge/_lock.py). The docstring references 'forge.memory.store._write_json' as the reference pattern, so any fix should be consistent across all callers.

### B5. [forge/telemetry/writer.py:20] fcntl.flock is Unix-only but README and INSTALL advertise Windows support

- **Session:** S16 (forge/telemetry/events.py + forge/telemetry/writer.py)
- **Category:** bug
- **Evidence:** writer.py:20 fcntl.flock(stream, fcntl.LOCK_EX) and writer.py:37 fcntl.flock(stream, fcntl.LOCK_SH). README L183-187 documents 'Windows (PowerShell): irm ... | iex'. INSTALL.md L15-19 same. The fcntl module does not exist on Windows; any call to TelemetryWriter.append or TelemetryWriter.read_all will crash with ModuleNotFoundError.
- **Fix:** Replace fcntl.flock with a cross-platform file lock (e.g. portalocker, or use msvcrt.locking on Windows / fcntl on POSIX via conditional import), or document that telemetry is POSIX-only and remove Windows claims from README/INSTALL.

### B6. [forge/context/result_store.py:15] ToolResultStore does not create its root directory, unlike TaskStore and TelemetryWriter which both call mkdir(parents=True) at init

- **Session:** S19 (forge/context/result_store.py + forge/context/__init__.py)
- **Category:** bug
- **Evidence:** Line 15-20: __init__ assigns self.root and self.index but never creates the directory. Compare forge/persistence.py:34 (TaskStore._load: self.path.parent.mkdir(parents=True, exist_ok=True)) and forge/telemetry/writer.py:18 (TelemetryWriter.append: self.path.parent.mkdir(parents=True, exist_ok=True)).
- **Fix:** Add self.root.mkdir(parents=True, exist_ok=True) in ToolResultStore.__init__ before assigning self.index.

### B7. [forge/memory/store.py:12] fcntl import crashes on Windows, contradicting documented Windows support

- **Session:** S21 (forge/memory/store.py + forge/memory/validation.py)
- **Category:** bug
- **Evidence:** Line 12: 'import fcntl' — fcntl is POSIX-only. README.md L183-187 and INSTALL.md L15-18 advertise Windows PowerShell install. Any import of store.py raises ModuleNotFoundError on Windows.
- **Fix:** Wrap fcntl import in a try/except ImportError with a fallback (e.g., portalocker or a no-op lock) or document Windows as unsupported until a cross-platform locking strategy is implemented.

### B8. [forge/memory/maintenance_service.py:288] Stale card detection uses substring search on JSON-serialized review-log records, causing false positives and O(n*m) performance

- **Session:** S23 (forge/memory/maintenance_schema.py + forge/memory/maintenance_service.py)
- **Category:** bug
- **Evidence:** Lines 288-291: `for card in old_cards: if card.card_id in blob: touched.add(card.card_id)` — serializes each review-log record to a JSON string via `json.dumps(record, sort_keys=True)`, then checks `card.card_id in blob` as substring match. A card_id like "card_1" would falsely match "card_10", "card_11", etc. embedded anywhere in the JSON (keys, other values, descriptions).
- **Fix:** Parse each record with `json.loads(blob)` and inspect structured fields that legitimately reference card_ids (e.g. `record.get("card_ids", [])`, `record.get("payload", {}).get("card_id")`). Use a set intersection approach instead of nested-loop substring search.

### B9. [forge/memory/review_log.py:10] Uses fcntl (Unix-only) but INSTALL.md documents Windows as a supported platform

- **Session:** S24 (forge/memory/maintenance_validator.py + forge/memory/review_log.py)
- **Category:** readme_drift
- **Evidence:** INSTALL.md:17-19 documents a PowerShell installer for Windows. review_log.py:10 imports fcntl for file locking (fcntl.flock at line 32), which is Unix-only and will raise ImportError on Windows.
- **Fix:** Replace fcntl.flock with a cross-platform equivalent (portalocker library, or use msvcrt.locking on Windows, or implement a lock file pattern with os.open/O_CREAT|O_EXCL)

---

## High-Severity Findings (28)

| # | File:Line | Category | Summary |
|---|---|---|---|
| H1 | forge/distribution/install.py:194 | bug | _stage_from_source calls src_plugin.iterdir() without verifying the directory exists, causing FileNotFoundError when plugin dist hasn't been built |
| H10 | forge/migrate_tasks.py:121 | bug | Missing os.fsync() after writing migrated entries risks data loss on crash |
| H11 | forge/migrate_tasks.py:24 | bug | _normalise_iso produces malformed ISO 8601 for non-UTC timezone offsets |
| H12 | forge/migrate_tasks.py:21 | readme_drift | Unknown task states silently default to 'completed', contradicting README's claim that unsupported behavior is recorded as unsupported |
| H13 | forge/plugin/bridge.py:24 | bug | No signal handling — SIGTERM/SIGINT kills the bridge mid-operation, potentially corrupting plugin_session_state.json |
| H15 | forge/review/diff.py:69 | bug | Unmerged entry handler hardcodes 'UU' status instead of parsing actual XY status from porcelain output |
| H16 | forge/review/evidence.py:55 | bug | Overbroad 'error' regex causes false-positive 'failed' classification when the word 'error' appears in non-failure context (e.g. 'error handling test passed') |
| H17 | forge/context/result_store.py:66 | bug | TOCTOU race condition between _consumed_from_index (unlocked read) and _record_expansion (locked write) can silently exhaust per-handle budget |
| H18 | forge/context/result_store.py:52 | bug | index.jsonl grows unboundedly with no compaction, pruning, or TTL, degrading all read operations over time |
| H19 | forge/memory/store.py:48 | bug | _corruption_warnings is shared mutable state cleared by every read method, losing previous warnings |
| H20 | forge/memory/store.py:173 | bug | edit_card does not validate edited fields against memory rules (blocklist, length) |
| H21 | forge/service.py:48 | duplicate | Duplicate FeedbackStore instances writing to the same file; service.py creates both a MemoryStore (which internally creates a FeedbackStore) and a separate standalone FeedbackStore, both pointing at memory_feedback.jsonl |
| H22 | forge/memory/maintenance_service.py:514 | bug | source_repo_id is incorrectly set to the same value as source_repo_root (a filesystem path), likely a copy-paste error |
| H23 | forge/memory/maintenance_validator.py:62 | slop | Dead parameter field_label in _memory_text_reason is never used in the function body |
| H24 | forge/memory/maintenance_validator.py:222 | duplicate | ~60 lines of near-identical validation logic duplicated between validate_create_pattern and validate_create_memory <br><sub>**Validation note:** ~30 lines of identical validation logic (not 60). Both functions have distinct requirements (recurrence refs, source task counts).</sub> |
| H25 | forge/plugin/opencode/src/index.ts:105 | readme_drift | FORGE_EXECUTABLE and FORGE_ALPHA_EXECUTABLE env vars used but undocumented in README/INSTALL |
| H26 | forge/plugin/opencode/src/forge-system.ts:121 | naming_drift | System prompt references tool 'forge_expand_tool_result' but actual MCP tool is named 'expand_tool_result' |
| H29 | forge/plugin/opencode/src/transcript.ts:80 | bug | Empty catch block in after() silently swallows all exceptions, making bugs undetectable in production |
| H3 | forge/distribution/install.py:61 | bug | _install_global_shims silently returns when loader.js or SKILL.md missing; install reports success with no OpenCode integration |
| H30 | README.md:221 | readme_drift | README documents FORGE_HOME/FORGE_ALPHA_HOME but loader.js and programRoot() use FORGE_PROGRAM/FORGE_ALPHA_PROGRAM |
| H31 | forge/plugin/opencode/src/index.ts:254 | bug | session.deleted closes the shared bridge, killing it for all other active sessions |
| H4 | forge/distribution/install.py:82 | slop | Comment references internal 'U5 build_release bootstrap' — meaningless in production source |
| H5 | forge/distribution/doctor.py:142 | bug | Empty or missing manifest keys produce false-positive checks because program_root() / '' returns program_root() itself |
| H6 | forge/distribution/doctor.py:148 | bug | Same empty-key false-positive applies to plugin existence check |
| H8 | scripts/build_release.py:100 | bug | Non-PyInstaller fallback creates a non-portable script with embedded absolute build paths, contradicting self-contained claim |
| H9 | forge/mcp_server.py:23 | bug | MCP start_task tool does not expose scope_mode parameter that the service layer supports |

---

## Medium-Severity Findings (74)

| # | File:Line | Category | Summary |
|---|---|---|---|
| H14 | forge/plugin/protocol.py:78 | bug | _persist_state() silently swallows OSError — persistent IO failures go undetected <br><sub>**Validation note:** OSError is caught and stored in self._persist_warning, surfaced in maintenance payloads. Not fully silent — only non-maintenance callers miss it. Downgraded: high → medium.</sub> |
| H2 | docs/INSTALL.md:50 | naming_drift | docs/INSTALL.md documents FORGE_RELEASE_BASE as an environment variable, but Python code only accepts --release-base as a CLI flag and does not read it from the environment <br><sub>**Validation note:** FORGE_RELEASE_BASE is consumed as an env var by shell installers (install.sh:16, install.ps1:12), not by Python CLI. Both paths work for their respective install methods. Downgraded: high → medium.</sub> |
| H7 | scripts/build_release.py:151 | slop | --check flag documented in README but not implemented in argparse <br><sub>**Validation note:** --check flag is documented in the file's own docstring (line 5), not in README. Category changed from readme_drift to slop. Downgraded: high → medium.</sub> |
| M1 | forge/distribution/install.py:234 | bug | _write_global_assets copies skill_src without checking if the source file exists, unlike the guarded loader_src copy above it |
| M10 | forge/distribution/doctor.py:86 | bug | Hardcoded /tmp worktree path in inline JS script breaks on Windows and non-standard Linux |
| M11 | forge/distribution/doctor.py:122 | readme_drift | README and INSTALL claim atomic activation but shim copy is not rolled back on partial failure <br><sub>**Validation note:** doctor.py is purely diagnostic; the install module would contain atomicity logic. File reference is correct.</sub> |
| M12 | forge/distribution/__init__.py:1 | slop | Module docstring lists 'upgrade' as a distinct capability but no upgrade code exists |
| M13 | scripts/install.sh:33 | naming_drift | FORGE_ALPHA_VERSION env var used in install.sh but undocumented in README and INSTALL |
| M14 | scripts/install.sh:16 | readme_drift | FORGE_RELEASE_BASE env var used in install.sh but undocumented in README and INSTALL |
| M15 | scripts/install.sh:46 | readme_drift | Version used in download URL may mismatch build_release.py output if v-prefix conventions differ |
| M16 | forge/lifecycle.py:16 | bug | apply_review allows None digest on passing review, causing apply_finish to always reject it |
| M17 | README.md:211 | readme_drift | README command table omits `forge config` and `forge config init` commands |
| M18 | forge/config.py:261 | slop | generate_commented_config() docstring claims 'every setting' but NotificationsConfig is missing 4 of 8 fields |
| M2 | README.md:211 | readme_drift | Command table omits `forge config init` which is implemented in the CLI |
| M20 | forge/persistence.py:106 | bug | Missing fsync on parent directory after os.replace in compaction, risking stale directory metadata on crash |
| M23 | forge/persistence.py:1 | unsubstantiated_claim | Both files use fcntl.flock (Unix-only) but README/INSTALL advertise Windows install — source-install platform limitation undocumented |
| M24 | forge/plugin/session_state.py:71 | duplicate | Atomic-write pattern duplicated between save() and transaction() within the same file |
| M25 | forge/task_state.py:47 | bug | response() mutates caller's extra dict via pop(), causing side effects |
| M26 | forge/plugin/protocol.py:42 | bug | _review_memory_skill() crashes if SKILL.md is missing or not packaged |
| M27 | forge/plugin/protocol.py:33 | bug | _wire() always returns ok:True even for warn/block decisions, making the ok field meaningless |
| M28 | forge/plugin/bridge.py:16 | bug | Response shape inconsistency across _error_response, _wire, and _maintenance_wire forces callers to handle three different schemas <br><sub>**Validation note:** Three different response shapes across _error_response, _wire, and _maintenance_wire.</sub> |
| M29 | forge/plugin/protocol.py:274 | bug | payload.get("arguments", {}) can return None when key is present with JSON null value |
| M3 | INSTALL.md:1 | readme_drift | FORGE_HOME and FORGE_ALPHA_HOME env vars are documented in README but absent from INSTALL.md |
| M30 | forge/plugin/protocol.py:12 | duplicate | Hardcoded schema_version in _wire and _error_response instead of using SCHEMA_VERSION constant |
| M31 | forge/plugin/opencode_adapter.py:19 | bug | Hardcoded schema_version instead of referencing SCHEMA_VERSION constant |
| M32 | forge/plugin/opencode_adapter.py:19 | duplicate | Duplicate error-response constructor shared between opencode_adapter.py and bridge.py with inconsistent field sets |
| M33 | forge/review/baseline.py:114 | bug | Broken symlinks cause crash in diff_trees: path.is_symlink() is True for broken symlinks but safe_path(..., must_exist=True) calls resolve(strict=True) which raises FileNotFoundError |
| M34 | forge/review/diff.py:81 | bug | Broken symlinks cause crash in capture_changes: same vulnerable pattern as baseline.py |
| M35 | forge/review/baseline.py:113 | duplicate | Content extraction logic for Change objects is nearly identical between diff_trees (baseline.py) and capture_changes (diff.py): both read file bytes, handle deletes via git cat-file/show, and sort by (path, status, content) |
| M36 | forge/review/verdict.py:293 | slop | Field 'unexplained_changed_files' is always initialized to [] and never populated anywhere in the function, making it dead code that contradicts the live 'out_of_scope_undeclared_files' field (line 303) |
| M38 | forge/review/__init__.py:1 | naming_drift | Exported function name review_repository does not match README tool name forge_review_changes |
| M39 | forge/telemetry/events.py:53 | bug | review_blocked field silently dropped when injected_memory_cards is None or empty |
| M4 | forge/cli.py:108 | readme_drift | forge config init subcommand is implemented but absent from README commands table |
| M40 | forge/context/governor.py:29 | bug | DANGEROUS regex misses rm -r -f and similar separate-flag variants |
| M41 | forge/context/governor.py:89 | bug | workdir missing from path_keys, allowing out-of-repo workdir to bypass unsafe_paths check |
| M42 | forge/context/governor.py:29 | bug | DANGEROUS regex misses git clean -d -f (separate flags before -f) |
| M43 | forge/context/formatter.py:6 | slop | estimate_tokens is dead code — defined in formatter.py but never imported or used by any production module |
| M44 | forge/context/result_store.py:26 | duplicate | _metadata and _consumed_from_index both independently read and parse the entire index.jsonl, duplicating I/O for every expand() call |
| M45 | forge/context/result_store.py:47 | bug | _consumed_from_index silently skips lines where chars field is non-numeric or missing, hiding data corruption |
| M46 | forge/memory/store.py:237 | bug | restore_card can create duplicate card_id in active store |
| M47 | forge/memory/store.py:259 | bug | merge_cards does not validate new card_id uniqueness when caller provides one |
| M48 | forge/memory/store.py:102 | duplicate | read_active() and load() duplicate the active-card reading logic with different error-reporting strategies |
| M49 | forge/config.py:65 | readme_drift | memory_max_chars default is 600 but all documentation says 400 |
| M5 | forge/cli.py:122 | bug | No-argument invocation silently starts MCP server instead of showing help |
| M50 | forge/memory/feedback_store.py:20 | duplicate | _timestamp() implementation is duplicated verbatim in feedback_store.py:20-21, store.py:57-58, and review_log.py:25-26 |
| M51 | forge/memory/feedback_store.py:41 | duplicate | JSONL read/parse logic is nearly identical to review_log.py:_read_all(); both check path.exists(), read_text, splitlines, skip blank lines, parse JSON with same error handling |
| M52 | forge/memory/feedback_store.py:10 | install_accuracy | fcntl import makes the module Unix-only; INSTALL.md and README advertise Windows install via PowerShell, but from-source Python code cannot run on Windows due to fcntl dependency |
| M53 | forge/memory/maintenance_service.py:180 | bug | review_count computed as max() of four unrelated metrics produces a misleading count that does not reflect total cards needing attention |
| M54 | forge/memory/maintenance_service.py:283 | other | Accesses private method _read_all() on the review_log object, creating fragile coupling to implementation details |
| M55 | forge/memory/maintenance_validator.py:258 | bug | Source task validation breaks on first error, hiding subsequent invalid source task IDs from user |
| M56 | forge/memory/maintenance_validator.py:321 | bug | validate_create_memory validates individual source tasks even when count != 1, producing confusing extra errors |
| M57 | forge/memory/scoring.py:224 | bug | select_cards backfill gap: empty rated pool wastes main_slots capacity |
| M6 | forge/cli.py:122 | readme_drift | Default-to-mcp behavior is undocumented in README and INSTALL |
| M60 | forge/plugin/opencode/src/index.ts:82 | readme_drift | resolveForgeExecutable resolves to dev-only .venv/bin/forge; production falls back to raw 'forge' on PATH |
| M61 | forge/plugin/opencode/src/forge-system.ts:62 | naming_drift | System prompt lists tools with 'forge_' prefix but MCP tools lack the prefix, creating ambiguity |
| M63 | forge/plugin/opencode/src/governor.ts:144 | unsubstantiated_claim | ContextGovernor.constructor accepts any string but throws for unrecognized modes at runtime <br><sub>**Validation note:** Constructor accepts any string but validates at line 144 (not 156). Finding substance is valid; line corrected.</sub> |
| M66 | forge/plugin/opencode/src/maintenance.ts:28 | bug | parseOperationsJSON silently drops non-record elements instead of rejecting them |
| M67 | forge/plugin/opencode/src/transport.ts:109 | bug | Unsolicited bridge output lines are silently dropped, masking protocol errors |
| M68 | forge/plugin/opencode/src/transport.ts:27 | naming_drift | transport.ts uses FORGE_PROGRAM/FORGE_ALPHA_PROGRAM but README only documents FORGE_HOME/FORGE_ALPHA_HOME |
| M7 | forge/distribution/install.py:54 | duplicate | String 'review-memory' hardcoded in 6+ locations across install.py and uninstall.py; should be a shared constant |
| M70 | forge/plugin/opencode/dist/index.js:12448 | naming_drift | runtimeRoot() uses FORGE_HOME/FORGE_ALPHA_HOME while programRoot() at line 13184 uses FORGE_PROGRAM/FORGE_ALPHA_PROGRAM — same file, different env var conventions |
| M71 | forge/plugin/opencode/loader.js:103 | bug | Env var FORGE_EXECUTABLE set after dist module import, so the dist top-level FORGE_EXECUTABLE const is always undefined at evaluation time |
| M74 | forge/plugin/opencode/src/index.ts:47 | bug | withDangerousAsks treats string "deny" and object {"*":"deny"} inconsistently |
| M75 | forge/plugin/opencode/src/governor.ts:60 | bug | resolvedWithExistingAncestors does not resolve symlinks in non-existing tail components, potentially bypassing path-safety checks |
| M76 | pyproject.toml:20 | readme_drift | forge-alpha entry point registered but undocumented in README/INSTALL commands table |
| M77 | scripts/generate_forge_system.py:61 | bug | Unhandled FileNotFoundError when PROMPT_PATH is missing |
| M78 | scripts/generate_forge_system.py:1 | readme_drift | From-source quickstart in INSTALL.md and README.md omits regeneration step |
| M8 | forge/distribution/install.py:45 | duplicate | _install_global_shims and _remove_global_shims duplicate identical plugin/skill path construction logic |
| M9 | forge/distribution/install.py:67 | readme_drift | FORGE_VERSION env var documented in INSTALL.md/README.md but not read by Python install code; only install.sh handles it |

---

## Low-Severity Findings (113)

| # | File:Line | Category | Summary |
|---|---|---|---|
| L1 | README.md:203 | readme_drift | From-source install instructions use `forge --help` but INSTALL.md uses `forge mcp` — they should be consistent |
| L10 | forge/distribution/doctor.py:64 | readme_drift | doctor does not validate manifest 'platform' field, despite install writing it and INSTALL claiming full integrity check |
| L100 | forge/plugin/opencode/loader.js:63 | bug | Manifest cache (_manifest) never invalidated — mid-session upgrades not detected |
| L101 | forge/plugin/opencode/dist/index.js:13220 | bug | bridgeArgs uses string.includes('python') heuristic which can false-positive on non-Python executables with 'python' in path |
| L102 | forge/plugin/opencode/src/index.ts:269 | bug | digester.clear called with potentially undefined sessionID on start_task |
| L103 | INSTALL.md:77 | install_accuracy | Documented build command runs test before build, but tests are .ts files needing compilation <br><sub>**Validation note:** Cannot confirm whether npm test handles TS compilation without seeing package.json test scripts.</sub> |
| L104 | INSTALL.md:44 | readme_drift | FORGE_HOME / FORGE_ALPHA_HOME env vars documented in README but not in INSTALL.md |
| L106 | forge/plugin/opencode/src/index.ts:281 | slop | Multiple empty catch blocks silently swallow errors; explanatory comments are lost in bundled dist/index.js |
| L107 | pyproject.toml:28 | slop | package-data includes broad *.json wildcard pulling in dev-only files (tsconfig.json, path_safety_cases.json) |
| L108 | pyproject.toml:30 | slop | package-data includes build.mjs — a Node.js build script, not a runtime dependency <br><sub>**Validation note:** The *.mjs wildcard would include build.mjs if it exists. Verify whether build.mjs actually exists in plugin/opencode/.</sub> |
| L109 | pyproject.toml:31 | slop | package-data includes commands/*.md — Node.js plugin documentation, not a Python runtime dependency |
| L11 | forge/distribution/paths.py:4 | readme_drift | FORGE_PROGRAM / FORGE_ALPHA_PROGRAM env vars documented in module docstring but absent from README |
| L110 | pyproject.toml:32 | slop | package-data includes TypeScript source files — compiled dist/index.js is the runtime artifact, .ts sources are bloat in the production wheel |
| L111 | packaging/forge.spec:1 | unsubstantiated_claim | Comment claims 'one-file executable' but EXE() does not explicitly set onefile/onedir, leaving binary structure to PyInstaller defaults <br><sub>**Validation note:** The Analysis→PYZ→EXE pattern is the standard PyInstaller one-file convention. No explicit flag needed.</sub> |
| L112 | packaging/forge.spec:16 | other | forge.spec bundles only index.js and index.js.map from dist/; pyproject.toml uses dist/*.js wildcard — if a new .js file appears in dist/ only pyproject.toml picks it up |
| L113 | packaging/forge.spec:52 | other | upx=True with empty upx_exclude risks corrupting bundled native extensions from mcp or its dependencies |
| L114 | scripts/generate_forge_system.py:45 | slop | Unused variable max_len computed but never referenced |
| L115 | scripts/generate_forge_system.py:100 | bug | Missing TS file in --check mode reports confusing 'stale' message |
| L116 | scripts/generate_forge_system.py:98 | slop | Bare sys.argv parsing without --help or unknown-flag handling |
| L12 | forge/distribution/paths.py:47 | other | Windows platform target hardcoded to x64, ignoring ARM64 architecture |
| L13 | scripts/build_release.py:25 | slop | import os is placed inside the function body instead of at module level |
| L16 | forge/config.py:56 | readme_drift | NotificationsConfig update-check and release-URL fields have no corresponding feature documentation |
| L17 | forge/config.py:132 | other | _build() silently ignores non-dict values for nested dataclass fields without warning |
| L18 | forge/config.py:252 | other | Legacy maintenance_review key silently ignored when both old and new keys exist in config |
| L19 | forge/lifecycle.py:56 | other | Degraded state has no lifecycle exit path — all functions reject it or are no-ops |
| L2 | INSTALL.md:99 | readme_drift | README documents `forge bridge` command but INSTALL.md Diagnostics section only shows `forge doctor` |
| L20 | forge/mcp_server.py:49 | slop | finish_task docstring documents memory_draft in detail but omits documentation for the memory_feedback parameter |
| L21 | forge/mcp_server.py:80 | slop | run_mcp() and main() duplicate core logic; main() creates an unused ArgumentParser |
| L22 | forge/service.py:359 | bug | _start_response mutates self.config_warnings to empty list on first call, suppressing warnings on subsequent idempotent calls |
| L23 | forge/migrate_tasks.py:9 | slop | Dead mapping: STATUS_TO_STATE['active'] maps to 'active' but active tasks are skipped in migrate() before convert() is ever called |
| L24 | forge/migrate_tasks.py:14 | other | Missing blank line between SCOPE_MAP dict definition and _valid_task_state function (PEP 8 violation) |
| L25 | forge/plugin/session_state.py:102 | slop | Bare `except Exception: raise` in transaction() is a no-op wrapper with no behavioral effect |
| L26 | forge/plugin/session_state.py:84 | bug | No directory fsync after os.replace, weakening crash-safety guarantee |
| L27 | forge/plugin/protocol.py:13 | duplicate | HIDDEN_OPERATIONS and MAINTENANCE_OPERATIONS duplicate 7 operation strings <br><sub>**Validation note:** All 8 strings in MAINTENANCE_OPERATIONS are in HIDDEN_OPERATIONS. Could be expressed as set difference.</sub> |
| L28 | forge/plugin/protocol.py:253 | bug | session_digest modifies task store outside a transaction, inconsistent with the rest of the protocol |
| L29 | forge/plugin/protocol.py:251 | bug | Calls to private methods self.service._bound_task() and self.service._emit() create fragile coupling |
| L3 | README.md:250 | other | Documentation section lists all docs/*.md files but does not link to docs/INSTALL.md |
| L30 | forge/plugin/bridge.py:35 | slop | # pragma: no cover comments in production source code |
| L31 | forge/plugin/opencode_adapter.py:17 | bug | Broad except Exception conflates ValueError from request()/validate_response() with transport failures, producing misleading error messages |
| L32 | forge/review/baseline.py:19 | duplicate | _git_with_index duplicates the subprocess error-handling pattern of git() in diff.py instead of reusing it |
| L34 | forge/review/baseline.py:104 | slop | diff_trees uses raw subprocess.run instead of the shared git() helper from diff.py, duplicating stdout/stderr/PIPE boilerplate |
| L35 | forge/review/verdict.py:294 | slop | Field 'mutation_ledger_summary' is always None with no logic to populate it, indicating an incomplete feature stub |
| L37 | forge/review/verdict.py:130 | slop | Redundant 'assert baseline_tree_id is not None' — already validated by 'baseline_available = bool(baseline_tree_id)' on line 111 <br><sub>**Validation note:** The assert is a type-narrowing idiom for static type checkers (mypy/pyright), not truly redundant.</sub> |
| L38 | forge/review/verdict.py:74 | duplicate | Return schema duplicated between _fail() (lines 74-96) and review_repository() (lines 285-303), requiring coordinated updates to both on any schema change |
| L39 | forge/review/verdict.py:146 | bug | Silent exception swallowing in diff_trees(repo, 'HEAD', baseline_tree_id) — any RepositoryInspectionError or CalledProcessError is ignored with no warning <br><sub>**Validation note:** pass is intentional and documented — HEAD may not exist in fresh repos. Not a bug, but a debug log would improve observability.</sub> |
| L4 | forge/cli.py:27 | other | forge version subcommand and forge --version flag produce inconsistent output |
| L40 | forge/review/__init__.py:1 | slop | Re-export of review_repository is unused by the entire codebase; no code imports from forge.review package level |
| L41 | forge/telemetry/events.py:53 | bug | injected_memory_cards=[] treated as falsy and silently dropped |
| L42 | forge/telemetry/events.py:11 | naming_drift | Parameter evidence_status does not match dict key claim_evidence_status or sister function convention |
| L43 | forge/telemetry/writer.py:22 | slop | Capacity check does not account for the size of the event about to be written |
| L44 | forge/telemetry/events.py:1 | readme_drift | No telemetry event type for the forge_review_changes mechanical gate featured prominently in README |
| L45 | forge/telemetry/honesty.py:26 | slop | Docstring contains speculative development-history comment referencing undocumented prior state |
| L46 | forge/telemetry/__init__.py:1 | naming_drift | Package __init__.py does not expose derive_honesty, creating a gap between the telemetry package's public surface and its actual contents <br><sub>**Validation note:** derive_honesty not exported but may be intentional — could be an internal function, not part of public API.</sub> |
| L47 | forge/context/formatter.py:1 | slop | formatter.py is an orphan module — not exported from context/__init__.py and its name ('formatter') is misleading for a token estimator |
| L48 | forge/context/governor.py:75 | bug | arguments.get('command') returning None produces str(None) instead of empty string fallback |
| L49 | forge/context/governor.py:105 | other | Redundant elif clause in _unsafe_paths — resolve(strict=False) already resolves symlinks, making the strict=True check duplicate |
| L5 | forge/cli.py:54 | bug | purge command lacks --config-root flag while install/doctor/uninstall all accept it |
| L50 | forge/context/result_store.py:73 | bug | expand() accepts start >= len(content) and returns empty chunk with complete=True instead of raising a clear error |
| L51 | forge/context/result_store.py:14 | slop | No docstrings or type-level documentation on ToolResultStore or any of its methods, obscuring purpose, handle format, locking semantics, and compatibility-debt status |
| L52 | forge/context/__init__.py:3 | naming_drift | ToolResultStore is defined in forge/context/result_store.py but excluded from the package's __all__ export list <br><sub>**Validation note:** ToolResultStore not in __all__ but may be intentional — package may only expose Governor types publicly.</sub> |
| L53 | forge/memory/card_factory.py:224 | other | source_repo_id and source_repo_root both set to task.repo_root — confusing duplication |
| L54 | forge/memory/card_factory.py:174 | slop | First element of honesty tuple (claim_evidence_status) is accepted but never consumed |
| L55 | forge/memory/card_factory.py:94 | bug | is_repo_specific returns False when ANY file fails the check, labeling mixed diffs as transferable |
| L56 | forge/memory/card_factory.py:73 | slop | derive_modules silently skips paths without a directory separator — files at repo root are omitted from modules |
| L57 | forge/memory/store.py:42 | naming_drift | File named 'deleted' but method named 'archived' — inconsistent terminology |
| L58 | forge/memory/store.py:274 | bug | merge_cards does not deduplicate supersedes list when card_ids contains duplicates |
| L59 | forge/memory/store.py:176 | slop | edit_card uses Any type for applies_when, bypassing type safety |
| L6 | forge/distribution/install.py:88 | slop | Message 'Building from source' is misleading; code copies pre-built assets, does not compile |
| L60 | forge/memory/store.py:78 | slop | Redundant ValueError catch since JSONDecodeError is a subclass of ValueError |
| L61 | forge/memory/store.py:313 | slop | rank function with inline imports is architectural debt living in the wrong module |
| L62 | forge/memory/inject.py:17 | slop | Docstring references 'spec lines 120-131, 364-383' with no context of what 'spec' refers to; this is a leftover from an internal specification document |
| L63 | forge/memory/inject.py:44 | bug | When max_chars is very small, block[:available] can truncate inside the [MEM card_id] header, producing a malformed prefix like '[M' instead of a valid card block |
| L64 | forge/memory/feedback_store.py:41 | other | read_feedback() loads the entire JSONL file into memory via path.read_text(); no pagination or size limit, could cause OOM on long-running systems with large feedback files |
| L65 | forge/memory/maintenance_service.py:156 | slop | Redundant condition: stale_count > 0 and stale_count >= 1 are identical |
| L66 | forge/memory/maintenance_service.py:259 | bug | packaging.version.Version import is inside the function body and may not be available; silent fallback suppresses update notifications |
| L67 | forge/memory/maintenance_service.py:615 | slop | The fallback `_op_name` function on line 615-616 silently returns class name for unknown types, which would produce an opaque operation string <br><sub>**Validation note:** _op_name fallback returns class name for unknown types — opaque but functional. Line corrected from 102 to 615.</sub> |
| L68 | forge/memory/maintenance_service.py:88 | other | Telemetry file is fully read into memory on every call to _telemetry_events, with no caching; called multiple times per batch operation |
| L69 | forge/memory/maintenance_validator.py:1 | other | from __future__ import annotations placed before module docstring, violating PEP 8 ordering |
| L7 | forge/distribution/doctor.py:66 | duplicate | Loader and skill global paths hardcoded in both doctor.py and install.py instead of centralized <br><sub>**Validation note:** Uses centralized _PLUGIN_DIR_NAME constant from paths.py. Duplication is within doctor.py itself, not cross-file.</sub> |
| L70 | forge/memory/review_log.py:10 | other | import fcntl separated from other stdlib imports by a blank line, misleadingly implying it is third-party |
| L73 | forge/memory/review_log.py:122 | other | _read_all loads entire JSONL file into memory — O(n) memory per read, repeated on each query call |
| L74 | forge/memory/scoring.py:178 | naming_drift | select_cards docstring omits the '*' wildcard for transferable cards |
| L75 | forge/memory/scoring.py:108 | naming_drift | relevance docstring says select_cards 'drops the card entirely' but wildcard cards pass through |
| L76 | forge/memory/scoring.py:126 | slop | Dead guard: max_possible <= 0.0 is unreachable because +5.0 for repo is unconditional |
| L77 | forge/memory/scoring.py:8 | slop | Opaque 'spec lines N' references throughout file, no published spec |
| L78 | forge/memory/__init__.py:1 | other | __init__.py does not expose scoring functions in public API |
| L79 | forge/memory/scoring.py:117 | other | Transferable cards (*) get repo_match=0.0 in relevance, penalizing relevance despite passing the hard filter |
| L80 | forge/plugin/opencode/src/index.ts:167 | readme_drift | FORGE_MCP_KEY env var used but undocumented in README/INSTALL |
| L81 | forge/plugin/opencode/src/index.ts:89 | bug | Multiple empty catch blocks silently swallow all errors with no logging |
| L82 | forge/plugin/opencode/src/index.ts:109 | bug | Unconditional delete of 'forge' MCP key may remove user's custom forge entry |
| L83 | forge/plugin/opencode/src/index.ts:85 | bug | import.meta.url path traversal breaks under bundlers that don't preserve source path depth |
| L84 | forge/plugin/opencode/src/index.ts:234 | other | experimental.chat.system.transform uses unstable OpenCode API |
| L85 | forge/plugin/opencode/src/governor.ts:74 | slop | isAbsolute(rel) check in escapesRoot is dead code on Linux and redundant on Windows |
| L86 | forge/plugin/opencode/src/governor.ts:163 | slop | Tool name normalization (trim().toLowerCase()) is duplicated in before() and fingerprint() |
| L87 | forge/plugin/opencode/src/governor.ts:110 | duplicate | dangerousCommandReason has overlapping regex branches that could be consolidated |
| L88 | forge/plugin/opencode/src/governor.ts:97 | bug | catch block in unsafePaths catches all errors but may mask programming errors |
| L89 | forge/plugin/opencode/src/transcript.ts:31 | naming_drift | SessionDigest type uses snake_case TypeScript properties (edited_files, edited_files_digest, test_runs) vs camelCase convention used in the rest of the codebase |
| L9 | forge/distribution/doctor.py:134 | bug | _check(False, ...) on line 134 is dead code because function returns immediately after, never reading 'ok' <br><sub>**Validation note:** _check is used for its side effect (printing to stdout); the ok assignment is dead but the print is meaningful. Line corrected from 133 to 134.</sub> |
| L90 | forge/plugin/opencode/src/transcript.ts:57 | bug | Non-standard 'path' field fallback in after() may match unintended tool parameters |
| L92 | forge/plugin/opencode/src/transport.ts:77 | duplicate | Duplicate Python bridge detection logic in bridgeArgs <br><sub>**Validation note:** Python bridge detection spans bridgeArgs (env var + heuristic) and ensureStarted. Complementary mechanisms, not true duplication.</sub> |
| L93 | forge/plugin/opencode/src/transport.ts:47 | bug | Python bridge executable resolution is not cached, causing repeated env-var reads |
| L94 | forge/plugin/opencode/src/maintenance.ts:26 | bug | parseOperationsJSON throws unhelpful SyntaxError without context on invalid JSON input |
| L95 | forge/plugin/opencode/src/maintenance.ts:69 | other | Internal context() method applies mode validation that dispatch('context') bypasses |
| L96 | forge/plugin/opencode/src/maintenance.ts:111 | bug | Empty catch blocks in recommend() and checkUpdate() silently swallow all bridge errors <br><sub>**Validation note:** Empty catch blocks are intentional per comments ('advisory operations must not break the host session'). Deliberate design tradeoff, not a bug.</sub> |
| L97 | forge/plugin/opencode/loader.js:94 | slop | Dead code in resolvePluginFactory: versionedModule.server and versionedModule.ForgeAlphaPlugin are never exported from dist/index.js <br><sub>**Validation note:** Cannot fully confirm without reading dist/index.js. Resolution paths may be defensive fallbacks rather than dead code.</sub> |
| L98 | forge/plugin/opencode/loader.js:82 | bug | getExecutable() hardcodes 'active/bin/forge' path while dist/index.js resolveExecutable() reads executable path from manifest — potential path disagreement |
| L99 | forge/plugin/opencode/dist/index.js:13684 | slop | plugin.ts wraps ForgeAlphaPlugin into {id, server} object as default export, making the source's named export unnecessary and the loader's fallback checks dead code <br><sub>**Validation note:** Bundled plugin wrappers are at lines 13684–13688, not 13586. Substance valid; line corrected.</sub> |
| M21 | forge/migrate_tasks.py:99 | bug | Active (in-progress) tasks silently dropped during migration with no warning to user <br><sub>**Validation note:** skipped_active counter is returned in the result dict but no user-facing warning is emitted. Downgraded: medium → low.</sub> |
| M22 | forge/persistence.py:98 | bug | Potential self-deadlock: _compact_unlocked calls all() which may try LOCK_SH while caller holds LOCK_EX <br><sub>**Validation note:** Deadlock is theoretical — all() would not call _load() because _load_unlocked() just populated _cache. Requires exceptional concurrent modification. Downgraded: medium → low.</sub> |
| M37 | README.md:244 | unsubstantiated_claim | Claims 'Unsupported behavior is recorded as unsupported, not presented as success' but the reviewed code has no mechanism to record or flag unsupported behavior <br><sub>**Validation note:** The claim is aspirational/marketing language describing philosophy, not a specific implemented feature. No dedicated 'unsupported' classification mechanism exists. Downgraded: medium → low.</sub> |
| M69 | forge/plugin/opencode/src/transport.ts:22 | readme_drift | Multiple undocumented environment variables in transport.ts not listed in README or INSTALL <br><sub>**Validation note:** Multiple FORGE env vars used in transport.ts are undocumented, but some are internal (FORGE_PYTHON_BRIDGE). Downgraded: medium → low.</sub> |
| M73 | INSTALL.md:41 | unsubstantiated_claim | Atomic install claim not verifiable from plugin code — no atomicity logic exists in reviewed files <br><sub>**Validation note:** Atomicity claim may be substantiated in install.py/shell-installer — reviewed files were plugin.ts, maintenance.ts which don't contain install logic. Downgraded: medium → low.</sub> |

---

## Nit Findings (20)

| # | File:Line | Category | Summary |
|---|---|---|---|
| L15 | scripts/build_release.py:27 | other | amd64 architecture not mapped to x64 unlike install.sh which handles it <br><sub>**Validation note:** Any non-arm architecture (including amd64) defaults to 'x64' through else branch. Functionally correct, less explicit than install.sh. Downgraded: low → nit.</sub> |
| N1 | README.md:221 | readme_drift | README mentions FORGE_HOME and FORGE_ALPHA_HOME in the command table footnotes but INSTALL.md has no equivalent env var documentation |
| N10 | forge/context/governor.py:13 | slop | Three blank lines between imports and class GovernorMode (PEP 8 mandates two) |
| N11 | forge/memory/store.py:245 | slop | merge_cards has no docstring despite being a complex mutation with side effects |
| N12 | forge/memory/maintenance_service.py:481 | slop | Defensive return with comment 'Should never happen' indicates a code path that cannot be tested and provides no actionable fallback |
| N13 | forge/memory/maintenance_validator.py:190 | bug | _validate_combine does not enforce non-empty why for merge/compact, inconsistent with create ops which require it |
| N14 | forge/memory/scoring.py:169 | slop | task parameter typed as Any instead of a typed Protocol |
| N15 | forge/plugin/opencode/src/index.ts:47 | slop | withDangerousAsks function name is unclear |
| N16 | forge/plugin/opencode/src/index.ts:82 | duplicate | resolveForgeExecutable and addForgeMcpConfig duplicate env var resolution concern <br><sub>**Validation note:** resolveForgeExecutable and addForgeMcpConfig share concern but have different scopes (base vs env-var-augmented). Defensible layering.</sub> |
| N17 | forge/plugin/opencode/src/plugin.ts:1 | slop | Import uses .ts extension which requires bundler support |
| N19 | scripts/generate_forge_system.py:2 | naming_drift | Source doc filename 'Forge Native Operating.md' doesn't match README terminology <br><sub>**Validation note:** Source doc filename uses 'Forge Native Operating' which doesn't match README terminology. Line corrected from 1 to 2.</sub> |
| N2 | forge/distribution/install.py:100 | unsubstantiated_claim | 'Atomic' activation claim in README/INSTALL not fully backed by try/except backup pattern |
| N20 | scripts/__init__.py:1 | slop | Minimal __init__.py with only a docstring |
| N3 | forge/distribution/__init__.py:2 | slop | Module docstring contains implementation history (refactor note) instead of user-facing documentation |
| N4 | scripts/build_release.py:93 | other | subprocess.run for PyInstaller has no timeout or output capture, risking hang in CI |
| N5 | forge/persistence.py:63 | other | reload() invalidates cache without synchronization, risk of None dereference on concurrent access |
| N6 | forge/persistence.py:77 | duplicate | JSON serialization parameters duplicated across both files could drift |
| N7 | forge/plugin/session_state.py:30 | other | SessionStateStore.__init__ does not validate that path is not empty or None |
| N8 | forge/plugin/opencode_adapter.py:16 | bug | _normalize() called outside try/except, so RecursionError on deeply nested payloads propagates unhandled |
| N9 | forge/review/__init__.py:0 | slop | Module-level docstring missing from the review package's public entry point |

---

## Per-Session Reports

| Session | Verdict | Findings | Files |
|---|---|---|---|
| S01 | issues | 14 | README.md + INSTALL.md |
| S02 | issues | 5 | forge/__init__.py + forge/cli.py |
| S03 | blocker | 10 | forge/distribution/install.py + forge/distribution/uninstall.py |
| S04 | issues | 7 | forge/distribution/doctor.py + forge/distribution/manifest.py |
| S05 | issues | 4 | forge/distribution/paths.py + forge/distribution/__init__.py |
| S06 | blocker | 10 | scripts/build_release.py + scripts/install.sh |
| S07 | issues | 7 | forge/config.py + forge/lifecycle.py |
| S08 | issues | 5 | forge/mcp_server.py + forge/service.py |
| S09 | issues | 11 | forge/persistence.py + forge/migrate_tasks.py |
| S10 | issues | 6 | forge/task_state.py + forge/plugin/session_state.py |
| S11 | issues | 11 | forge/plugin/bridge.py + forge/plugin/protocol.py |
| S12 | issues | 4 | forge/plugin/opencode_adapter.py + forge/plugin/__init__.py |
| S13 | issues | 6 | forge/review/baseline.py + forge/review/diff.py |
| S14 | issues | 6 | forge/review/evidence.py + forge/review/verdict.py |
| S15 | issues | 3 | forge/review/__init__.py |
| S16 | blocker | 6 | forge/telemetry/events.py + forge/telemetry/writer.py |
| S17 | issues | 2 | forge/telemetry/honesty.py + forge/telemetry/__init__.py |
| S18 | issues | 8 | forge/context/formatter.py + forge/context/governor.py |
| S19 | blocker | 8 | forge/context/result_store.py + forge/context/__init__.py |
| S20 | issues | 4 | forge/memory/cards.py + forge/memory/card_factory.py |
| S21 | blocker | 12 | forge/memory/store.py + forge/memory/validation.py |
| S22 | issues | 6 | forge/memory/inject.py + forge/memory/feedback_store.py |
| S23 | issues | 9 | forge/memory/maintenance_schema.py + forge/memory/maintenance_service.py |
| S24 | issues | 9 | forge/memory/maintenance_validator.py + forge/memory/review_log.py |
| S25 | issues | 8 | forge/memory/scoring.py + forge/memory/__init__.py |
| S26 | issues | 15 | forge/plugin/opencode/src/plugin.ts + forge/plugin/opencode/src/index.ts |
| S27 | issues | 8 | forge/plugin/opencode/src/governor.ts + forge/plugin/opencode/src/forge-system.ts |
| S29 | issues | 9 | forge/plugin/opencode/src/maintenance.ts + forge/plugin/opencode/src/transport.ts |
| S30 | issues | 7 | forge/plugin/opencode/loader.js + forge/plugin/opencode/dist/index.js |
| S31 | issues | 8 | forge/plugin/opencode/dist/index.js.map |
| S32 | issues | 8 | packaging/forge.spec + pyproject.toml |
| S33 | issues | 7 | scripts/generate_forge_system.py + scripts/__init__.py |

---

## Cross-File Notes (by session)

**S01** (README.md + INSTALL.md):
> README.md and INSTALL.md agree on the global install curl command, Python 3.12+ requirement, and the existence of forge doctor/install/uninstall/purge. The main drifts are: (1) the final command in from-source setup differs (forge --help vs forge mcp), (2) the command table in README omits forge config init, (3) FORGE_HOME/FORGE_ALPHA_HOME env vars are not covered in INSTALL.md, (4) docs/INSTALL.md documents FORGE_RELEASE_BASE as an env var but Python only accepts --release-base as a CLI flag. The code in install.py has two missing existence checks (plugin dist dir, skill source file) that can crash source-mode installs.

**S02** (forge/__init__.py + forge/cli.py):
> forge/__init__.py and forge/cli.py are internally consistent: __version__ from __init__.py is imported (cli.py L7) and used for both --version flag (L82) and version subcommand (L28). No duplicates between the two files. README/INSTALL claim version 0.1.0-alpha.1 which matches __init__.py L3. The README commands table omits the 'config' command defined in cli.py L108. The undocumented default-to-mcp on no-args (cli.py L122) is the most notable drift between code and documentation.

**S03** (forge/distribution/install.py + forge/distribution/uninstall.py):
> install.py and uninstall.py are structurally consistent: InstallMixin and UninstallMixin share the same DistributionService composition (forge/distribution/__init__.py:59), use the same path constants from paths.py, and operate on the same manifest/shims/skill paths. The `_active_manifest_path()` method is defined in InstallMixin (install.py:36-37) and type-stubbed in UninstallMixin (uninstall.py:23), which is correct for the mixin pattern. Both files hardcode `'review-memory'` as a literal instead of sharing a constant. The `_install_global_shims` / `_remove_global_shims` methods duplicate identical path-building logic. The PyInstaller .spec (packaging/forge.spec:15-23) maps data files to a directory structure compatible with the `Path(__file__).resolve().parents[2]` traversal in `_write_global_assets`, so that path works in the frozen executable. However, the fallback wrapper in scripts/build_release.py:105-111 hardcodes the developer's REPO_ROOT, which breaks on user machines — this is a build-system issue outside the reviewed file scope. The README.md and INSTALL.md consistently describe `forge install`, `forge uninstall`, `forge purge`, and `forge doctor`; all four commands exist and are delegated correctly via cli.py. The `FORGE_VERSION` env var documented in both docs is not consumed by the Python code, creating a doc-vs-code gap.

**S04** (forge/distribution/doctor.py + forge/distribution/manifest.py):
> doctor.py and manifest.py are at different abstraction levels — manifest.py provides low-level I/O primitives (read, write, backup, restore, sha256), while doctor.py consumes those indirectly via install.py's mixin. doctor.py does not import manifest.py directly; it relies on _read_active_manifest() which is defined in InstallMixin (install.py:39) and inherited through DistributionService(InstallMixin, DoctorMixin, UninstallMixin). The key structural inconsistency is that doctor.py treats empty manifest keys as valid input (returning program_root() / '' == program_root()), producing false positives for missing executable/plugin entries. Additionally, install._stage_from_source creates version manifests with a nested 'assets' sub-object while the active manifest uses flat keys — this dual structure is intentional but fragile if a developer mixes up which manifest they are reading. README and INSTALL make stronger claims about 'atomic' installation than the code actually guarantees.

**S05** (forge/distribution/paths.py + forge/distribution/__init__.py):
> The assigned files are internally consistent: __init__.py imports and re-exports every name declared in paths.py's public (and private) API. DistributionService uses _opencode_config_root from paths.py via the config_root property. There is no contradiction between the two files. However, the __init__.py docstring's claim of 'upgrade' support has no code backing anywhere in the distribution package. README/INSTALL.md claims about FORGE_HOME, FORGE_ALPHA_HOME, and the 'atomically applies configuration changes' guarantee are partially supported: manifest atomic write is correct, but FORGE_PROGRAM env vars are undocumented at the README level.

**S06** (scripts/build_release.py + scripts/install.sh):
> The two files are broadly consistent with each other in platform labeling (linux-x64, macos-arm64, etc.) but have minor mapping differences (install.sh handles 'amd64' while build_release.py does not). install.sh documents FORGE_RELEASE_BASE and FORGE_ALPHA_VERSION env vars that are unreferenced in README/INSTALL. The README documents a --check flag that build_release.py does not implement. The primary blocker is that install.sh's default (no env vars) path cannot resolve 'latest' from an invalid URL, making the documented curl|bash one-liner fail. The secondary blocker is macOS checksum command mismatch. Additionally, build_release.py's non-PyInstaller fallback produces a non-portable bundle contradicting the 'self-contained' claim in README/INSTALL.

**S07** (forge/config.py + forge/lifecycle.py):
> config.py and lifecycle.py are well-separated with no duplicate logic. Config defines configuration dataclasses and file I/O; lifecycle defines the task state machine. Cross-file consistency is good: lifecycle.py relies on TaskSnapshot and TERMINAL_STATES from task_state.py (not config.py), and config.py's ValidationConfig constraints align with lifecycle's review/finish workflow. The main cross-document inconsistencies are: (1) README omits `forge config init` which both config.py and cli.py implement; (2) config.py's `_COMMENTED_CONFIG` is missing 4 NotificationsConfig fields that would appear in the output of `forge config init`. No naming conflicts between files.

**S08** (forge/mcp_server.py + forge/service.py):
> The MCP tool signatures in mcp_server.py largely mirror the service methods in service.py, but one significant gap exists: scope_mode is not exposed. The service supports 'strict' and 'warning' (service.py:62), but the MCP wrapper hard-codes 'strict' by omission. All other tool signatures (review_changes, finish_task, submit_outcome, expand_tool_result) are fully consistent between the two files. Version (0.1.0-alpha.1, in forge/__init__.py:3) matches README. Runtime root defaults to ~/.forge/ with FORGE_HOME/ FORGE_ALPHA_HOME env overrides (service.py:31-34) matching README claims.

**S09** (forge/persistence.py + forge/migrate_tasks.py):
> Both files implement JSON-Lines persistence with fcntl.flock advisory locking. Key cross-file inconsistencies: (1) migrate_tasks.py omits os.fsync() after writes, while persistence.py includes it — durability gap. (2) Both duplicate the same JSON serialization parameters (sort_keys, separators) — consolidation would prevent drift. (3) Both share the same TaskSnapshot model and JSON-Lines format, making the files broadly compatible. (4) SCOPE_MAP in migrate_tasks.py maps legacy 'warn' to 'warning' which is a valid scope_mode value verified against service.py:62. (5) README claims 'unsupported behavior is recorded as unsupported' but migrate_tasks.py:21 silently maps unknown legacy states to 'completed' (terminal success), contradicting the README. (6) Active tasks are silently dropped during migration with no logging — this data-loss behavior is undocumented in both README and INSTALL.

**S10** (forge/task_state.py + forge/plugin/session_state.py):
> 1. task_state.py and session_state.py are independent subsystems with no direct coupling: task_state.py defines the core task lifecycle data model (TaskSnapshot, TaskState, TERMINAL_STATES, response()), while session_state.py manages plugin session-mode and maintenance-owner persistence. 2. TaskSnapshot has a `session_digest` field (line 30) whose shape could reference data managed by SessionStateStore, but there is no formal schema coupling or cross-validation between the two. 3. Both files lack __all__ exports, making public API surface implicit. 4. session_state.py (forge/plugin/) is under plugin ownership, task_state.py (forge/) is core — the INSTALL/README distinction between 'global install' and 'from source' mirrors this architecture split but neither file documents its ownership boundary. 5. The fcntl Windows blocker in session_state.py is systemic — 8 forge modules (including persistence.py, memory/store.py, memory/feedback_store.py, memory/review_log.py, telemetry/writer.py, context/result_store.py, migrate_tasks.py) all use fcntl. A cross-platform fix at a single abstraction point is strongly recommended rather than per-file patches.

**S11** (forge/plugin/bridge.py + forge/plugin/protocol.py):
> bridge.py and protocol.py are largely consistent in purpose: bridge.py reads stdin, calls protocol.py's PluginProtocolBackend.handle(), and writes stdout. Key issues: (1) bridge.py's _error_response returns a different schema than either of protocol.py's two response builders (_wire vs _maintenance_wire), forcing the JS plugin caller to handle three shapes. (2) Both files hardcode schema_version=1 instead of using the SCHEMA_VERSION constant from protocol.py. (3) bridge.py unconditionally passes default mode='report' and GovernorCapabilities() to PluginProtocolBackend — if the README's claim about 'host-native safety friction' requires different capabilities, the bridge doesn't allow them to be injected. (4) Against README/INSTALL: the 'forge bridge' command documented in README line 218 is plausibly backed by bridge.py's if __name__ block, but the CLI wiring (click/typer entry point) is not visible in these files; the SKILL.md reference in protocol.py line 42 validates INSTALL.md's '/review-memory skill' claim.

**S12** (forge/plugin/opencode_adapter.py + forge/plugin/__init__.py):
> Cross-file consistency: __init__.py cleanly re-exports OpenCodeAdapter. protocol.py has a second hardcoded "schema_version": 1 in _wire() (line 514) while _maintenance_wire() (line 507) correctly uses SCHEMA_VERSION — the same inconsistency exists within protocol.py itself. bridge.py _error_response() (line 13) also hardcodes schema_version. The plugin/ package has three nearly-identical error-response dict constructors (opencode_adapter.py fallback, bridge.py _error_response, protocol.py _maintenance_wire) with slightly different field sets. README/INSTALL describe the TypeScript plugin at forge/plugin/opencode/; the Python adapter reviewed here is backend infrastructure not exposed in docs — no drift found. env vars FORGE_HOME/FORGE_ALPHA_HOME from README are not referenced in these files, which is correct since they are backend infra, not CLI code.

**S13** (forge/review/baseline.py + forge/review/diff.py):
> baseline.py and diff.py are consistent in their public API surface: baseline.py imports Change, RepositoryInspectionError, safe_path, and validate_repo from diff.py, so there is a single source of truth for these types. The main cross-file consistency concern is the duplicated content-extraction logic in diff_trees (baseline.py:113-135) and capture_changes (diff.py:81-93) — they follow the same pattern but differ slightly in how deleted content is retrieved (git cat-file blob vs git show). Both also share the same broken-symlink crash vulnerability. The _git_with_index helper (baseline.py) and git helper (diff.py) follow the same error-handling pattern; they could be consolidated. README/INSTALL claims about baseline-backed review, scope inspection, and digest computation are substantiated by these files (capture_tree, diff_trees, capture_changes, digest_changes). The FORGE_HOME runtime-root override documented in README is handled at the caller (service.py:default_runtime_root), not in these review modules, which is acceptable since sweep_temp_dir takes an optional runtime_root parameter.

**S14** (forge/review/evidence.py + forge/review/verdict.py):
> evidence.py and verdict.py are consistent: classify_evidence() is correctly imported on verdict.py line 11 and called at lines 88 and 275. The function signature matches between files. README's workflow descriptions (Git delta, scope, syntax, validation evidence) are backed by review_repository(). However, the README's claim about 'unsupported behavior is recorded as unsupported' has no code counterpart. README's 'FORGE_HOME' / 'FORGE_ALPHA_HOME' env vars and the 'forge doctor' / 'forge install' commands are outside these files' scope. The stale-review freshness check referenced in README lifecycle is not in these files (it belongs in forge_finish_task). Version alignment is consistent: INSTALL says Python 3.12+, code uses Python 3.10+ features (str | None) and datetime.UTC (3.11+) which is compatible.

**S15** (forge/review/__init__.py):
> forge/review/__init__.py vs README.md: README describes the review tool as forge_review_changes (a CLI tool / system-prompt function), but the Python package exports review_repository (a library function). The ForgeService.review_changes method (service.py:114) bridges the gap, calling review_repository internally. All other review submodules (baseline.py, diff.py, evidence.py, verdict.py) are imported directly by service.py and tests, bypassing __init__.py entirely. INSTALL.md does not reference the review package directly, so no drift there. No contradictions found between __init__.py and the other review submodules — the import chain (.verdict → .baseline, .diff, .evidence) is valid and consistent.

**S16** (forge/telemetry/events.py + forge/telemetry/writer.py):
> events.py and writer.py are consistent in their dict-based JSONL protocol. Both import from __future__ import annotations and use typing.Any. The test file (tests/test_telemetry.py) imports and tests both modules. Cross-file issue: events.py's naming inconsistency (evidence_status vs claim_evidence_status) is not mirrored in writer.py but creates a caller-facing inconsistency. Writer.py's fcntl usage is the single biggest cross-cutting concern — it contradicts the Windows platform claims in both README.md and INSTALL.md.

**S17** (forge/telemetry/honesty.py + forge/telemetry/__init__.py):
> honesty.py and __init__.py are consistent in typing conventions and import style (both use from __future__ import annotations). However, __init__.py treats TelemetryWriter as the sole public export while honesty.py contains a function (derive_honesty) consumed by forge/service.py directly via deep import. Against README: derive_honesty aligns with the 'observed passed' / 'observed failed' validation evidence statuses shown in finish receipts (README L50-L51) and the 'A failed command was reframed as success' honesty concern (README L23). No drift between code and documented claims. Against INSTALL: no relevant claims to compare.

**S18** (forge/context/formatter.py + forge/context/governor.py):
> formatter.py (estimate_tokens) and governor.py (ContextGovernor) are functionally independent — no shared logic or duplication. formatter.py is unused in production code (dead code, only referenced in tests). governor.py is the production runtime policy engine, fully exercised. Both files correctly implement the safety-friction claims in README (destructive command detection, out-of-repo path blocking), but with gaps: missing path key workdir and missing separate-flag variants in DANGEROUS regexes. No README/INSTALL drift — the documented features (Context Governor, safety friction) either exist in governor.py or live in separate modules.

**S19** (forge/context/result_store.py + forge/context/__init__.py):
> forge/context/__init__.py re-exports governor classes but not ToolResultStore, while service.py imports ToolResultStore directly from result_store. This is inconsistent — ToolResultStore lives in the forge.context package but is excluded from its public API. The Python ToolResultStore (fr_ handles) is compatibility debt per EXTRACTION_LEDGER.md paragraph 2: 'Retaining that endpoint is compatibility debt, not evidence of per-call plugin transport.' This is undocumented in the code. Both TaskStore and TelemetryWriter create their parent directories; ToolResultStore does not — a clear behavioral inconsistency across the codebase.

**S20** (forge/memory/cards.py + forge/memory/card_factory.py):
> cards.py defines the data model (MemoryCard, AppliesWhen) with field-level validators. card_factory.py is the sole producer of MemoryCard instances from finish_task drafts. The two files are structurally consistent. Key observations: (1) source_repo_id and source_repo_root are duplicates in the factory — scoring.py:194 uses source_repo_id for matching against repo_root, so it works but is semantically confusing; (2) use_as defaults to "" in the factory and is populated only later via maintenance_service.py — intentional by design; (3) cross_task_pattern entry type is not produced by the factory but is used by maintenance_service.py:533/560 for pattern-merge cards — not dead code; (4) no README/INSTALL drift was found because these are internal data-structure modules whose behavior is not exposed in user-facing documentation.

**S21** (forge/memory/store.py + forge/memory/validation.py):
> store.py and validation.py are functionally independent (store: persistence, validation: content rules). The gap is that store.py never calls validation functions — add_card and edit_card bypass validate_memory_text and validate_why entirely, relying solely on MemoryCard.__post_init__ for structural type checks. card_factory.py does call validation before calling the store, creating a fragile two-gate architecture where bypassing the factory silently produces unvalidated data. Terminology: validation.py uses 'memory' for the text field (matching MemoryCard.memory), consistent with docs. README claims ~/.forge/memory storage path matches MemoryConfig.storage_root default. FORGE_HOME env var handling is not in these files. fcntl usage is a blocker for Windows support claimed in README/INSTALL.

**S22** (forge/memory/inject.py + forge/memory/feedback_store.py):
> FeedbackStore between files: service.py creates two FeedbackStore instances pointing at the same memory_feedback.jsonl (lines 48-50) — one via MemoryStore (store.py:46) and one standalone. Only the standalone one is used for writing (service.py:270); the MemoryStore-owned instance is used only for reading via store.py:298. This is confusing and a latent bug if someone later writes through the 'wrong' instance. — _timestamp() duplicated across 3 files (feedback_store.py, store.py, review_log.py). — JSONL read/parse pattern duplicated across feedback_store.py and review_log.py. — format_brief in inject.py is correctly called from service.py:350 with [(0, card)] tuples, matching its documented signature. — MemoryCard has fields (use_as, source_task_ids, supersedes, superseded_by) that are documented as intentionally excluded from injection (inject.py:24-25). — README.md and INSTALL.md are consistent with the code's behavior: memory cards injected as brief, feedback stored in JSONL files, runtime data under ~/.forge/. No naming drift between doc claims and code identifiers.

**S23** (forge/memory/maintenance_schema.py + forge/memory/maintenance_service.py):
> maintenance_schema.py and maintenance_service.py are internally consistent: all operation types defined in OPERATION_TYPES (schema L102-110) are handled in _apply_one (service L414-483) and mapped in _OP_NAMES (service L604-612). The parse_operation function (schema L131-216) correctly maps all operation strings to their dataclass types, and the service uses isinstance checks that match. README and INSTALL claims about /review-memory (pruning/merging/restoring/backfilling) are backed by the operation types (archive/merge/restore/create), though 'pruning' maps to archive_card and 'backfilling' maps to create_memory_card/create_pattern_card. The INSTALL source-build step `forge mcp` would exercise these services indirectly through the MCP bridge. The most serious issue is the stale-card substring-search bug (blocker), which would produce incorrect maintenance recommendations in production. The source_repo_id copy-paste (high) is the second-largest risk, potentially corrupting memory-card metadata for downstream consumers.

**S24** (forge/memory/maintenance_validator.py + forge/memory/review_log.py):
> The two files are internally consistent: review_log.py handles logging (batch lifecycle, maintenance failures, update/recommendation events) and maintenance_validator.py handles per-operation validation rules. Both files correctly reference /review-memory terminology matching README.md:234. Neither file references FORGE_HOME/FORGE_ALPHA_HOME (abstracted by caller). The primary cross-file inconsistency is platform: maintenance_validator.py is pure Python and cross-platform, while review_log.py depends on Unix-only fcntl, contradicting INSTALL.md:17-19 Windows support claim. Both files share a minor consistency issue — maintenance_validator.py's `_memory_text_reason` accepts a dead `field_label` parameter while review_log.py's `_append` accepts generic dict records; neither file duplicates the other's responsibility.

**S25** (forge/memory/scoring.py + forge/memory/__init__.py):
> forge/memory/__init__.py is a minimal re-export hub (MemoryCard, MemoryStore) and does not expose scoring.py functions. This is consistent with scoring.py's private-by-convention design (underscore-prefixed helpers), but the public API omission means consumers must import from the private submodule directly. The feedback_aggregate dict structure (keys: 'helpful','unused','misleading','unknown','n' from store.py:read_feedback_aggregate, plus 'wins'/'losses' from scoring.py:add_outcome_history) is consistent between scoring.py and store.py. README.md does not detail the scoring algorithm but links to docs/MEMORY.md; INSTALL.md has no overlap with scoring code. No major README/INSTALL drift found — the scoring module's behavior does not contradict documented install steps or feature claims.

**S26** (forge/plugin/opencode/src/plugin.ts + forge/plugin/opencode/src/index.ts):
> plugin.ts and index.ts are consistent: plugin.ts imports ForgeAlphaPlugin (named export) from index.ts and wraps it in { id:'forge', server: ForgeAlphaPlugin }. index.ts also exports ForgeAlphaPlugin as default. Both use consistent 'Alpha' naming. The only concern is the .ts extension import in plugin.ts (requires bundler). W.r.t README/INSTALL: (a) the plugin implements 'What Forge Adds' features (permissions, /review-memory, event-driven lifecycle hooks) — all backed by code. (b) FORGE_EXECUTABLE, FORGE_ALPHA_EXECUTABLE, FORGE_MCP_KEY env vars are undocumented. (c) The XDG data path assumption (~/.local/share) conflicts with cross-platform portability claim. (d) The resolveForgeExecutable .venv dev-path is inconsistent with README's 'no source checkout needed' message. (e) The 'forge doctor', 'forge install', 'forge uninstall', 'forge purge', 'forge version' commands are Python CLI concerns, not expected in this plugin. (f) INSTALL.md plugin dev sequence matches the file structure.

**S27** (forge/plugin/opencode/src/governor.ts + forge/plugin/opencode/src/forge-system.ts):
> CROSS-FILE CONSISTENCY: forge-system.ts (system prompt) and governor.ts (enforcement) are structurally consistent — the governor implements path-escape checks, dangerous-command detection, and duplicate-call blocking that the system prompt references. However, there is a naming mismatch: forge-system.ts references 'forge_expand_tool_result' which does not exist in governor.ts or anywhere in the plugin; the actual tool is 'expand_tool_result' in the Python MCP server. Also, forge-system.ts line 156 claims 'The Context Governor runs automatically. Do not call it' but governor.ts supports OFF/REPORT/ACTIVE modes, and the automatic-running behavior only applies in ACTIVE mode — the system prompt does not qualify this claim.

README/INSTALL DRIFT: README.md's command table (lines 211-219) lists CLI commands (forge install, forge doctor, forge mcp, etc.) which are not present in either assigned TypeScript file — they live in the Python backend. INSTALL.md's plugin dev instructions (lines 72-82) are consistent with the TypeScript code — there is no drift vs the assigned files.

FORGE_VERSION env var is documented in README line 189 and INSTALL line 34 but not referenced in either assigned TypeScript file (it lives in the Python backend and shell scripts) — not a drift, just different ownership.

**S29** (forge/plugin/opencode/src/maintenance.ts + forge/plugin/opencode/src/transport.ts):
> Both files use the same BridgeResponse type consistently. maintenance.ts imports and uses BridgeClient from transport.ts correctly. Both use BRIDGE_TIMEOUT_MS from transport.ts indirectly via the request method. The bridge request/response protocol (JSON over stdin/stdout) is consistent between the caller (maintenance.ts dispatch) and the transport implementation (transport.ts request/ensureStarted). Main concern: env-var surface in transport.ts is undocumented in README/INSTALL; parseOperationsJSON behavior differs in strictness from typical input validation; the mode-check divergence between context() and dispatch('context') could cause subtle state mismatches.

**S30** (forge/plugin/opencode/loader.js + forge/plugin/opencode/dist/index.js):
> loader.js and dist/index.js share the same programRoot() logic (XDG paths) but diverge in executable resolution: loader.js hardcodes 'active/bin/forge' while dist/index.js reads from the active.json manifest. The env var contract (loader sets FORGE_EXECUTABLE for dist to consume) is broken due to timing — the dist module evaluates top-level env reads at import time, before the loader sets the variable. Naming conventions differ across files: transport/program resolution uses FORGE_PROGRAM (not in README). The loader's resolvePluginFactory has fallback branches that are permanently unreachable against the current dist/index.js export shape. The source TypeScript (src/index.ts) exports ForgeAlphaPlugin as a named export and default function, but the bundler wraps it into {id, server} via plugin.ts, creating an impedance mismatch with the loader's factory resolver.

**S31** (forge/plugin/opencode/dist/index.js.map):
> Source map (index.js.map) is generated by esbuild with sourcemap:true. It correctly references ../src/index.ts and node_modules/zod/v4/... as sources. sourcesContent is embedded inline, making the map 884K vs 493K JS bundle. No issues with source map structure or linkage (//# sourceMappingURL=index.js.map present). Plugin entry (plugin.ts -> index.ts) correctly exports ForgeAlphaPlugin as the default. TRANSPORT.md env vars (FORGE_EXECUTABLE, FORGE_PYTHON_BRIDGE, etc.) are used consistently across index.ts and transport.ts. The FORGE_FINISH_TOOL constant ("finish_task") matches the OpenCode internal tool name used in tool.execute.before/after handlers. No cross-file naming inconsistencies detected.

**S32** (packaging/forge.spec + pyproject.toml):
> forge.spec and pyproject.toml are roughly consistent on core plugin files (dist/index.js, dist/index.js.map, loader.js, SKILL.md). The spec explicitly lists individual files; pyproject.toml uses wildcards. The spec may miss plugin/opencode/commands/*.md which pyproject.toml includes — if OpenCode plugin discovery requires this file at runtime in a frozen install, the spec needs updating. pyproject.toml package-data includes several development/build artifacts (src/*.ts, *.mjs, commands/*.md, broad *.json) that inflate the production wheel but are not runtime requirements. Both files match README version 0.1.0-alpha.1 and the forge.cli:main entry point. The forge-alpha alias in pyproject.toml:20 is undocumented in README/INSTALL.

**S33** (scripts/generate_forge_system.py + scripts/__init__.py):
> scripts/__init__.py and scripts/generate_forge_system.py have no internal consistency issues. generate_forge_system.py and build_release.py both use the same REPO_ROOT pattern (Path(__file__).resolve().parents[1]) — consistent. However, build_release.py uses argparse for CLI while generate_forge_system.py uses raw sys.argv — inconsistent design approach in sibling scripts. README and INSTALL describe the operating protocol and system prompt injection but never cite docs/Forge Native Operating.md by name, making it hard for a reader to connect the doc reference in the script's docstring to the documented feature.

---

## Top Blocker Themes

### 1. Windows support broken (5 of 9 blockers)

8 files import `fcntl` (Unix-only): `forge/persistence.py`, `forge/migrate_tasks.py`,
`forge/plugin/session_state.py`, `forge/telemetry/writer.py`, `forge/context/result_store.py`,
`forge/memory/store.py`, `forge/memory/feedback_store.py`, `forge/memory/review_log.py`.
README.md L183-187 and INSTALL.md L15-19 advertise Windows PowerShell install
(`install.ps1` exists), but the Python runtime crashes on Windows. `build_release.py`
targets win32 but cannot build a Windows bundle from this code.

### 2. Installer URL broken on all platforms

`install.sh:39` and `install.ps1:24` fetch `$RELEASE_BASE/latest.txt` — a GitHub download
URL that requires a tag component. The default "latest" install path is broken everywhere.

### 3. macOS install broken

`install.sh:61` uses `sha256sum` which does not exist on macOS (ships `shasum -a 256`).
Script header claims Linux/macOS support.

### 4. Atomicity claim overstated

README.md:191 & INSTALL.md:41 say "atomically applies configuration changes" but the
try/except in `install.py` only catches Python exceptions, not SIGKILL/power loss.
`loader.js` has zero backup/rollback logic.

### 5. "Unsupported behavior recorded" claim has no backing

README.md:245 claims unsupported behavior is recorded as unsupported; no such mechanism
exists in `evidence.py` or `verdict.py`.

---

## Coverage Note

`scripts/install.ps1` was not in the original 33-session pairing. It was reviewed
separately and confirmed to share the `latest.txt` URL blocker with `install.sh`.
S07 required one flash retry (first attempt did not finish writing JSON); no pro fallback
was used.
