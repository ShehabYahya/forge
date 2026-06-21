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
});

test("plugin escalates without throwing and compacts the actual OpenCode output field", async () => {
  const root = tmpDir();
  const previousHome = process.env.FORGE_ALPHA_HOME;
  const previousDataHome = process.env.XDG_DATA_HOME;
  process.env.FORGE_ALPHA_HOME = root;
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
    if (previousHome === undefined) delete process.env.FORGE_ALPHA_HOME;
    else process.env.FORGE_ALPHA_HOME = previousHome;
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
