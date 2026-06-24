import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import {
  applyForgePermissions,
  DANGEROUS_BASH_PERMISSION_PATTERNS,
  ForgeAlphaPlugin,
} from "./src/index.ts";

function tmpDir(): string {
  const dir = join(tmpdir(), "forge-plugin-test-" + randomBytes(8).toString("hex"));
  mkdirSync(dir, { recursive: true });
  return dir;
}

test("config installs native ask rules without weakening deny", () => {
  const config: Record<string, unknown> = { permission: { bash: "allow", external_directory: "allow" } };
  applyForgePermissions(config);
  const permission = config.permission as Record<string, unknown>;
  const bash = permission.bash as Record<string, string>;
  assert.equal(bash["*"], "allow");
  for (const pattern of DANGEROUS_BASH_PERMISSION_PATTERNS) {
    assert.equal(bash[pattern], "ask", pattern);
  }
  assert.equal(permission.external_directory, "ask");

  const denied: Record<string, unknown> = { permission: { bash: "deny", external_directory: "deny" } };
  applyForgePermissions(denied);
  assert.deepEqual(denied.permission, { bash: "deny", external_directory: "deny" });
  const commands = denied.command as Record<string, { template: string }>;
  assert.match(commands["review-memory"].template, /forge_memory_review/);
});

test("config registers Forge MCP under forge key when missing", async () => {
  const root = tmpDir();
  const prevExe = process.env.FORGE_EXECUTABLE;
  process.env.FORGE_EXECUTABLE = "forge";
  try {
    const hooks = await ForgeAlphaPlugin({
      worktree: root,
      directory: root,
      client: { tui: { showToast: async () => undefined } },
    } as never);
    const config: Record<string, unknown> = { mcp: {} };
    await hooks.config?.(config as never);
    const servers = config.mcp as Record<string, Record<string, unknown>>;
    const forge = servers["forge"];
    assert.equal(forge.type, "local");
    assert.deepEqual(forge.command, ["forge", "mcp"]);
    assert.equal(forge.enabled, true);
  } finally {
    if (prevExe === undefined) delete process.env.FORGE_EXECUTABLE;
    else process.env.FORGE_EXECUTABLE = prevExe;
    rmSync(root, { recursive: true, force: true });
  }
});

test("config preserves existing forge MCP entry", async () => {
  const root = tmpDir();
  try {
    const hooks = await ForgeAlphaPlugin({
      worktree: root,
      directory: root,
      client: { tui: { showToast: async () => undefined } },
    } as never);
    const config: Record<string, unknown> = { mcp: { "forge": { type: "local", command: "custom-forge" } } };
    await hooks.config?.(config as never);
    const servers = config.mcp as Record<string, Record<string, unknown>>;
    const forge = servers["forge"];
    assert.equal(forge.command, "custom-forge");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("config honors disabled forge MCP entry", async () => {
  const root = tmpDir();
  try {
    const hooks = await ForgeAlphaPlugin({
      worktree: root,
      directory: root,
      client: { tui: { showToast: async () => undefined } },
    } as never);
    const config: Record<string, unknown> = { mcp: { "forge": { state: "disabled" } } };
    await hooks.config?.(config as never);
    const servers = config.mcp as Record<string, unknown>;
    assert.deepEqual(servers["forge"], { state: "disabled" });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("plugin escalates without throwing and compacts the actual OpenCode output field", async () => {
  const root = tmpDir();
  const previousHome = process.env.FORGE_HOME;
  const previousDataHome = process.env.XDG_DATA_HOME;
  process.env.FORGE_HOME = root;
  process.env.XDG_DATA_HOME = join(root, "data");
  const toasts: unknown[] = [];
  try {
    const hooks = await ForgeAlphaPlugin({
      worktree: root,
      directory: root,
      client: { tui: { showToast: async (value: unknown) => { toasts.push(value); } } },
    } as never);
    const before = hooks["tool.execute.before"]!;
    await assert.doesNotReject(
      before(
        { tool: "bash", sessionID: "session-a", callID: "call-a" },
        { args: { command: "rm -rf harmless-target" } },
      ),
    );
    assert.equal(toasts.length, 1);

    const after = hooks["tool.execute.after"]!;
    const original = Array.from({ length: 600 }, (_, index) => `output line ${index + 1}`).join("\n") + "\n";
    const outputDir = join(root, "data", "opencode", "tool-output");
    mkdirSync(outputDir, { recursive: true });
    const outputPath = join(outputDir, "tool_test");
    writeFileSync(outputPath, original);
    const output = {
      title: "test",
      output: "...output truncated...\npreview only",
      metadata: { truncated: true, outputPath },
    };
    await after(
      { tool: "bash", sessionID: "session-a", callID: "call-a", args: {} },
      output,
    );
    assert.notEqual(output.output, original);
    assert.match(output.output, /Handle: fo_[0-9a-f]{32}/);
    assert.match(output.output, /L1-L\d+:/);

    const handle = output.output.match(/fo_[0-9a-f]{32}/)![0];
    const expandTool = hooks.tool!.forge_expand_output;
    const expanded = await expandTool.execute(
      { handle, start_line: 249, end_line: 251 },
      { sessionID: "session-a" } as never,
    );
    assert.match(String(expanded), /output line 250/);
  } finally {
    if (previousHome === undefined) delete process.env.FORGE_HOME;
    else process.env.FORGE_HOME = previousHome;
    if (previousDataHome === undefined) delete process.env.XDG_DATA_HOME;
    else process.env.XDG_DATA_HOME = previousDataHome;
    rmSync(root, { recursive: true, force: true });
  }
});

test("plugin duplicate blocking is isolated by session", async () => {
  const root = tmpDir();
  try {
    const hooks = await ForgeAlphaPlugin({
      worktree: root,
      directory: root,
      client: { tui: { showToast: async () => undefined } },
    } as never);
    const before = hooks["tool.execute.before"]!;
    const args = { filePath: join(root, "file.txt") };
    await before({ tool: "read", sessionID: "one", callID: "1" }, { args });
    await before({ tool: "read", sessionID: "two", callID: "2" }, { args });
    await assert.rejects(
      before({ tool: "read", sessionID: "one", callID: "3" }, { args }),
      /duplicate read/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("review-memory tool proxies maintenance mode and blocks denied tools", async () => {
  const root = tmpDir();
  const previousHome = process.env.HOME;
  const previousForgeHome = process.env.FORGE_HOME;
  process.env.HOME = root;
  process.env.FORGE_HOME = root;
  mkdirSync(root, { recursive: true });
  writeFileSync(join(root, "tasks.jsonl"), `${JSON.stringify({
    task_id: "task-memory",
    state: "active",
    task_text: "review memory",
    repo_root: root,
    expected_files: [],
    host_session_id: "session-review",
    scope_mode: "strict",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    schema_version: 1,
    injected_memory_cards: [],
  })}\n`);
  try {
    const hooks = await ForgeAlphaPlugin({
      worktree: root,
      directory: root,
      client: { tui: { showToast: async () => undefined } },
    } as never);
    const review = hooks.tool!.forge_memory_review;
    const started = JSON.parse(String(await review.execute(
      { action: "start" },
      { sessionID: "session-review" } as never,
    )));
    assert.equal(started.mode, "memory_review");

    const context = JSON.parse(String(await review.execute(
      { action: "context" },
      { sessionID: "session-review" } as never,
    )));
    assert.equal(context.mode, "memory_review");
    assert.deepEqual(context.blocked_tools, ["edit", "write", "bash"]);

    const before = hooks["tool.execute.before"]!;
    await assert.rejects(
      before(
        { tool: "edit", sessionID: "session-review", callID: "call-maint" },
        { args: { filePath: join(root, "notes.md") } },
      ),
      /maintenance mode/,
    );

    const finished = JSON.parse(String(await review.execute(
      { action: "finish", status: "completed" },
      { sessionID: "session-review" } as never,
    )));
    assert.equal(finished.status, "completed");

    await assert.doesNotReject(
      before(
        { tool: "edit", sessionID: "session-review", callID: "call-free" },
        { args: { filePath: join(root, "notes.md") } },
      ),
    );

    await hooks.event?.({
      event: {
        type: "session.deleted",
        properties: { sessionID: "session-review" },
      },
    } as never);
  } finally {
    if (previousHome === undefined) delete process.env.HOME;
    else process.env.HOME = previousHome;
    if (previousForgeHome === undefined) delete process.env.FORGE_HOME;
    else process.env.FORGE_HOME = previousForgeHome;
    rmSync(root, { recursive: true, force: true });
  }
});

test("review-memory runs without an active lifecycle task and deny-by-default gating", async () => {
  const root = tmpDir();
  const previousForgeHome = process.env.FORGE_HOME;
  process.env.FORGE_HOME = root;
  try {
    const hooks = await ForgeAlphaPlugin({
      worktree: root,
      directory: root,
      client: { tui: { showToast: async () => undefined } },
    } as never);
    const review = hooks.tool!.forge_memory_review;
    await review.execute({ action: "start" }, { sessionID: "standalone" } as never);
    const context = JSON.parse(String(await review.execute(
      { action: "context" }, { sessionID: "standalone" } as never,
    )));
    assert.equal(context.mode, "memory_review");
    assert.ok(context.allowed_tools.includes("finish_task"));
    const before = hooks["tool.execute.before"]!;
    await assert.doesNotReject(before(
      { tool: "finish_task", sessionID: "standalone", callID: "allowed" },
      { args: {} },
    ));
    await assert.rejects(before(
      { tool: "bash", sessionID: "standalone", callID: "denied" },
      { args: {} },
    ), /maintenance mode/);
    await hooks.event?.({
      event: { type: "session.deleted", properties: { sessionID: "standalone" } },
    } as never);
  } finally {
    if (previousForgeHome === undefined) delete process.env.FORGE_HOME;
    else process.env.FORGE_HOME = previousForgeHome;
    rmSync(root, { recursive: true, force: true });
  }
});
