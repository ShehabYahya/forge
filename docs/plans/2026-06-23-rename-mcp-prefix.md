# Plan: Rename MCP Prefix from `forge-alpha_` to `forge_`

**Goal:** Rename tool names from `forge-alpha_forge_start_task` to `forge_start_task` by changing the MCP server key from `"forge-alpha"` to `"forge"` and dropping the redundant `forge_` prefix from bare tool names.

**Key Insight:** After the change, agent-visible tool names are **unchanged** — `forge_start_task` now comes from `forge` (MCP key) + `start_task` (bare name) instead of `forge-alpha` + `forge_start_task`. This means the system prompt, contract doc, governor message, and all user-facing text that references agent-visible tool names require **zero content changes**.

---

## Wave 1: Python MCP Server Key

### 1.1 `forge/mcp_server.py:18`
```python
# OLD
mcp = FastMCP("forge-alpha")
# NEW
mcp = FastMCP("forge")
```

---

## Wave 2: Python Bare Tool Names

### 2.1 `forge/mcp_server.py:10-16` — PUBLIC_TOOLS tuple
```python
# OLD
PUBLIC_TOOLS = (
    "forge_start_task",
    "forge_review_changes",
    "forge_finish_task",
    "forge_submit_outcome",
    "forge_expand_tool_result",
)
# NEW
PUBLIC_TOOLS = (
    "start_task",
    "review_changes",
    "finish_task",
    "submit_outcome",
    "expand_tool_result",
)
```

### 2.2 `forge/mcp_server.py:22-66` — `@mcp.tool()` functions
Rename all five functions and their `_service.*` calls:

| Old function | New function |
|---|---|
| `forge_start_task` | `start_task` |
| `forge_review_changes` | `review_changes` |
| `forge_finish_task` | `finish_task` |
| `forge_submit_outcome` | `submit_outcome` |
| `forge_expand_tool_result` | `expand_tool_result` |

Corresponding `_service.forge_*` calls become `_service.*`.

### 2.3 `forge/service.py` — Method names
All five `ForgeService` methods drop the `forge_` prefix:

| Old method | New method |
|---|---|
| `forge_start_task` | `start_task` |
| `forge_review_changes` | `review_changes` |
| `forge_finish_task` | `finish_task` |
| `forge_submit_outcome` | `submit_outcome` |
| `forge_expand_tool_result` | `expand_tool_result` |

### 2.4 `forge/config.py:23-28` — MaintenanceReviewConfig.allow tuple
```python
# OLD
"forge_start_task",
"forge_review_changes",
"forge_finish_task",
"forge_submit_outcome",
"forge_expand_tool_result",
# NEW
"start_task",
"review_changes",
"finish_task",
"submit_outcome",
"expand_tool_result",
```

---

## Wave 3: TypeScript Plugin

### 3.1 `forge/plugin/opencode/src/index.ts:19` — DEFAULT_FORGE_MCP_KEY
```typescript
// OLD
const DEFAULT_FORGE_MCP_KEY = "forge-alpha";
// NEW
const DEFAULT_FORGE_MCP_KEY = "forge";
```

### 3.2 `forge/plugin/opencode/src/index.ts:80-101` — Fix `addForgeMcpConfig` bug
Currently `addForgeMcpConfig` hardcodes `"forge-alpha"` instead of using the resolved key. This is a latent bug. Fix by parameterizing:

```typescript
function addForgeMcpConfig(config: Record<string, unknown>, forgeMcpKey: string): void {
  const existing = config.mcpServers && typeof config.mcpServers === "object"
    ? config.mcpServers as Record<string, unknown>
    : {};

  const prev = existing[forgeMcpKey];
  if (prev && typeof prev === "object" && !Array.isArray(prev)) {
    const prevState = (prev as Record<string, unknown>).state;
    if (prevState === "disabled" || prevState === "deny") return;
  }

  const executable = process.env.FORGE_ALPHA_EXECUTABLE?.trim() || "forge-alpha";

  config.mcpServers = {
    ...existing,
    [forgeMcpKey]: {
      type: "stdio",
      command: executable,
      args: ["mcp"],
    },
  };
}
```

Update call site at ~line 209:
```typescript
// OLD
addForgeMcpConfig(config as unknown as Record<string, unknown>);
// NEW
addForgeMcpConfig(config as unknown as Record<string, unknown>, forgeMcpKey);
```

### 3.3 `forge/plugin/opencode/src/index.ts:268` — FORGE_FINISH_TOOL usage
No change to this line (it uses the constant), but constant value changes in maintenance.ts.

### 3.4 `forge/plugin/opencode/src/maintenance.ts:5` — FORGE_FINISH_TOOL constant
```typescript
// OLD
export const FORGE_FINISH_TOOL = "forge_finish_task";
// NEW
export const FORGE_FINISH_TOOL = "finish_task";
```

**Rationale:** OpenCode passes **bare** MCP tool names (without server key prefix) to plugin hooks. Evidence: the current code compares `input.tool === FORGE_FINISH_TOOL` where `FORGE_FINISH_TOOL = "forge_finish_task"`, and if OpenCode passed the full qualified name `"forge-alpha_forge_finish_task"`, this would be dead code. Since the code works, OpenCode must strip the MCP namespace. After the rename, the bare tool name becomes `"finish_task"`. The constant MUST be updated to match.

### 3.5 `forge/plugin/opencode/src/plugin.ts:4` — Plugin ID
**Decision: DO NOT CHANGE.** The plugin ID `"forge-alpha"` is separate from the MCP key and changing it risks breaking OpenCode plugin state tracking. Leave as `"forge-alpha"`.

---

## Wave 4: Test Files

### 4.1 `forge/plugin/opencode/system-transform.test.ts` — MCP key references
All `"forge-alpha"` → `"forge"` (the MCP key):

- Line 39: `connectedResult(key = "forge-alpha")` → `key = "forge"`
- Lines 75,81,87,93,99: `getForgeMcpStatus(client, "forge-alpha")` → `"forge"`
- Lines 110,118,124,130,136,149,156,162: `waitForForgeMcpConnected(client, "forge-alpha", ...)` → `"forge"`
- Lines 200,212,223: `"forge-alpha": {status: ...}` → `"forge": {status: ...}`
- Line 233: Test description `"forge-alpha key missing"` → `"forge key missing"`
- Line 330: `"forge-alpha": {status: "connected"}` → `"forge": {status: "connected"}`

### 4.2 `tests/test_config.py` — Allow list assertions
Lines 40-45 and 192-197:
```python
# OLD
"forge_start_task",
"forge_review_changes",
"forge_finish_task",
"forge_submit_outcome",
"forge_expand_tool_result",
# NEW
"start_task",
"review_changes",
"finish_task",
"submit_outcome",
"expand_tool_result",
```

### 4.3 `tests/test_documentation.py:8-13` — Public tools doc test
```python
# OLD
documented = set(re.findall(r"`(forge_[a-z_]+)`", contract.split("Every response", 1)[0]))
removed_name = "forge_" + "prepare_" + "context"
documented.discard(removed_name)
assert documented == set(PUBLIC_TOOLS)
# NEW
documented = set(re.findall(r"`(forge_[a-z_]+)`", contract.split("Every response", 1)[0]))
documented = {name.removeprefix("forge_") for name in documented}
removed_name = "prepare_context"
documented.discard(removed_name)
assert documented == set(PUBLIC_TOOLS)
```

### 4.4 Python test files — service method calls
Rename all `service.forge_start_task(...)` → `service.start_task(...)` (same for all 5 methods) across:

- `tests/test_service_contract.py` (lines 9-14, 20-21, 29-32)
- `tests/test_lifecycle.py` (lines 8, 16, 19, 25-26, 33, 35, 41, 43, 49, 52, 67, 79, 82, 88, 95, 97, 106-107)
- `tests/test_task_persistence.py` (lines 8-9, 17, 28-29, 40, 48-49)
- `tests/test_finish_task_integration.py` (lines 49-50, 60, 88, 119, 122, 158, 171, 178, 197)
- `tests/test_plugin_adapter.py` (line 32)
- `tests/test_memory_cards.py` (lines 164-165)

### 4.5 `tests/test_memory_maintenance_gating.py:105`
```python
# OLD
assert "forge_finish_task" in result["payload"]["allowed_tools"]
# NEW
assert "finish_task" in result["payload"]["allowed_tools"]
```

### 4.6 `tests/test_mcp_contract.py`
No changes needed — uses `PUBLIC_TOOLS` which is already updated in Wave 2.

### 4.7 `forge/plugin/opencode/plugin.test.ts` — Maintenance mode gating test
Lines 208 and 211 reference `"forge_finish_task"` as the bare tool name that gets checked against `allowed_tools`:

```typescript
// Line 208 — OLD
assert.ok(context.allowed_tools.includes("forge_finish_task"));
// Line 208 — NEW
assert.ok(context.allowed_tools.includes("finish_task"));

// Line 211 — OLD
{ tool: "forge_finish_task", sessionID: "standalone", callID: "allowed" },
// Line 211 — NEW
{ tool: "finish_task", sessionID: "standalone", callID: "allowed" },
```

**Rationale:** `allowed_tools` comes from `MaintenanceReviewConfig.allow` (now `"finish_task"`). The `maintenance.before()` hook checks `input.tool` against this set. OpenCode passes bare MCP tool names to plugin hooks (confirmed by the fact that `FORGE_FINISH_TOOL = "forge_finish_task"` currently works with `input.tool`). After rename, bare name is `"finish_task"`.

### 4.8 `docs/WALKTHROUGH.md` — Python code examples
Lines 38-41, 60 call methods that lose their `forge_` prefix:

```python
# Line 38 — OLD
started = service.forge_start_task("add feature", str(repo), ["feature.py"], "walkthrough-session")
# Line 38 — NEW
started = service.start_task("add feature", str(repo), ["feature.py"], "walkthrough-session")

# Line 40 — OLD
reviewed = service.forge_review_changes(started["task_id"], [{"status": "passed", "command": "python -m compileall"}])
# Line 40 — NEW
reviewed = service.review_changes(started["task_id"], [{"status": "passed", "command": "python -m compileall"}])

# Line 41 — OLD
finished = service.forge_finish_task(started["task_id"], True, "Added feature", [{"status": "passed"}])
# Line 41 — NEW
finished = service.finish_task(started["task_id"], True, "Added feature", [{"status": "passed"}])

# Line 60 — OLD
result = service.forge_submit_outcome(False, "Backend unavailable", "adapter outage", repo_root=str(root / "repo"))
# Line 60 — NEW
result = service.submit_outcome(False, "Backend unavailable", "adapter outage", repo_root=str(root / "repo"))
```

---

## Wave 5: Regeneration

### 5.1 Regenerate `forge/plugin/opencode/src/forge-system.ts`
Run `python scripts/generate_forge_system.py` to ensure the file is in sync with `docs/Forge Native Operating.md`. *(No content change expected — agent-visible tool names are unchanged.)*

---

## Things That MUST NOT Change (Bug Prevention Checklist)

| Item | Reason |
|---|---|
| Binary name `forge-alpha` (CLI, scripts, release artifacts) | Separate from MCP key; the executable name is `forge-alpha` |
| `FORGE_ALPHA_EXECUTABLE` env var default | Points to the binary, not the MCP key |
| Runtime paths `~/.forge-alpha/` | Storage paths, not MCP identity |
| `forge_expand_output` tool name | Native OpenCode plugin tool, not MCP |
| `forge_memory_review` tool name | Native OpenCode plugin tool, not MCP |
| `MAINTENANCE_TOOL` constant | References native plugin tool |
| System prompt text (`FORGE_SYSTEM_BOOTSTRAP`) | Agent-visible tool names unchanged |
| `docs/Forge Native Operating.md` | Agent-visible tool names unchanged |
| `docs/FORGE_ALPHA_CONTRACT.md` | Agent-visible tool names unchanged |
| `forge/context/governor.py:95` | References agent-visible name `forge_expand_tool_result` which is unchanged |
| `forge/plugin/protocol.py` hidden operations | Bridge ops, not MCP tools |
| `forge/plugin/opencode/commands/review-memory.md` | References `forge_memory_review` (native) |
| `forge/skills/review-memory/SKILL.md` | References `forge_memory_review` (native) |
| GitHub workflows release artifacts | Binary name stays `forge-alpha` |
| Install scripts (`install.sh`, `install.ps1`) | Binary name stays `forge-alpha` |
| `pyproject.toml` name and entry point | Binary name stays `forge-alpha` |
| `forge/distribution.py` plugin dir `plugins/forge-alpha/` | This is the OpenCode plugin directory name, not the MCP key. Changing it would break distribution. Keep as-is. |
| `FORGE_MCP_KEY` env var (line 149) | Already parameterized via `resolveForgeMcpKey`, no change needed |
| `forge/cli.py:11,63` CLI name references | Binary name stays `forge-alpha` |
| `forge/plugin/opencode/src/plugin.ts:4` plugin ID | Plugin ID `"forge-alpha"` is separate from MCP key; changing it risks breaking plugin state tracking |

---

## Validation Plan

1. **Python tests:** `python -m pytest tests/ -x` — all 26 test files must pass
2. **TypeScript build:** `cd forge/plugin/opencode && npm run build` — must compile without errors
3. **TypeScript tests:** `cd forge/plugin/opencode && npm test` — all tests must pass
4. **Doc regeneration:** `python scripts/generate_forge_system.py --check` — must produce no diff
5. **Manual verification of MCP identity uses:** No bare `"forge-alpha"` string (as MCP key) should remain in plugin source or tests. Exclude intentional references (binary name, plugin ID, paths):
   ```bash
   rg '"forge-alpha"' forge/plugin/opencode/src/ forge/plugin/opencode/*.test.ts
   ```
   Expected false positives (must manually verify each is NOT an MCP key):
   - `src/index.ts:91` — `FORGE_ALPHA_EXECUTABLE` default (binary name, correct to keep)
   - `src/plugin.ts:4` — Plugin registration ID (correct to keep)
   - `src/transport.ts` — Binary paths (correct to keep)
6. **Manual verification of stale tool names:** No `forge_start_task`, `forge_review_changes`, `forge_finish_task`, `forge_submit_outcome`, or `forge_expand_tool_result` should remain as Python identifiers (method/function names or config values) in:
   ```bash
   rg 'forge_start_task|forge_review_changes|forge_finish_task|forge_submit_outcome|forge_expand_tool_result' forge/mcp_server.py forge/service.py forge/config.py forge/plugin/protocol.py
   ```
   Exception: `forge/context/governor.py:95` which references the agent-visible tool name `forge_expand_tool_result` — this is correct and should remain.
7. **Grepgrep for leftover old method names in tests:**
   ```bash
   rg '\.forge_start_task|\.forge_review_changes|\.forge_finish_task|\.forge_submit_outcome|\.forge_expand_tool_result' tests/
   ```
   Should return zero results (no Python test should call old method names).

---

## Risk Analysis

| Risk | Likelihood | Mitigation |
|---|---|---|
| `addForgeMcpConfig` hardcoding bug blocks custom `FORGE_MCP_KEY` | Was already broken; fix included in this plan | Wave 3.2 parameterizes the function |
| Test uses `forge-alpha` as server key not caught | Every test file audited | Wave 4 covers all known test files |
| Some file uses `forge_*` method name that grep missed | Low; comprehensive grep across py/ts | Validation plan steps 6-7 |
