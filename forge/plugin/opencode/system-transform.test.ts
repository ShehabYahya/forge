import test from "node:test";
import assert from "node:assert/strict";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { mkdirSync, rmSync } from "node:fs";
import {
  ForgeAlphaPlugin,
  getForgeMcpStatus,
  waitForForgeMcpConnected,
} from "./src/index.ts";
import {
  FORGE_SYSTEM_BOOTSTRAP,
  FORGE_SYSTEM_MARKER_OPEN,
  FORGE_SYSTEM_MARKER_CLOSE,
  forgeSystemBlock,
  hasForgeSystemMarker,
} from "./src/forge-system.ts";

function tmpDir(): string {
  const dir = join(tmpdir(), "forge-sys-test-" + randomBytes(8).toString("hex"));
  mkdirSync(dir, { recursive: true });
  return dir;
}

/**
 * Build a fake OpenCode client whose mcp.status() resolves to the given
 * server map (or a sequence of maps for readiness-wait tests).
 */
function fakeClient(
  statusFn: () => Promise<unknown>,
): { mcp: { status: () => Promise<unknown> }; tui: { showToast: () => Promise<void> } } {
  return {
    mcp: { status: statusFn },
    tui: { showToast: async () => undefined },
  };
}

function connectedResult(key = "forge-alpha"): unknown {
  return { data: { [key]: { status: "connected" } } };
}

// ---------------------------------------------------------------------------
// Module-level unit tests for forge-system.ts helpers
// ---------------------------------------------------------------------------

test("FORGE_SYSTEM_BOOTSTRAP is the verbatim protocol text, not empty", () => {
  assert.ok(FORGE_SYSTEM_BOOTSTRAP.length > 1000);
  assert.match(FORGE_SYSTEM_BOOTSTRAP, /Forge Native Operating Protocol/);
  assert.match(FORGE_SYSTEM_BOOTSTRAP, /forge_start_task/);
  // Marker must never appear inside the bootstrap itself.
  assert.ok(!FORGE_SYSTEM_BOOTSTRAP.includes(FORGE_SYSTEM_MARKER_OPEN));
  assert.ok(!FORGE_SYSTEM_BOOTSTRAP.includes(FORGE_SYSTEM_MARKER_CLOSE));
});

test("forgeSystemBlock wraps bootstrap with forge_system tags", () => {
  const block = forgeSystemBlock();
  assert.ok(block.startsWith(FORGE_SYSTEM_MARKER_OPEN + "\n"));
  assert.ok(block.endsWith("\n" + FORGE_SYSTEM_MARKER_CLOSE));
  assert.ok(block.includes(FORGE_SYSTEM_BOOTSTRAP));
});

test("hasForgeSystemMarker detects and rejects correctly", () => {
  assert.ok(hasForgeSystemMarker("x\n" + FORGE_SYSTEM_MARKER_OPEN + "\ny"));
  assert.ok(!hasForgeSystemMarker("just plain text"));
  assert.ok(!hasForgeSystemMarker(""));
});

// ---------------------------------------------------------------------------
// getForgeMcpStatus unit tests
// ---------------------------------------------------------------------------

test("getForgeMcpStatus returns connected status for matching key", async () => {
  const client = fakeClient(async () => connectedResult());
  const status = await getForgeMcpStatus(client, "forge-alpha");
  assert.equal(status, "connected");
});

test("getForgeMcpStatus returns undefined when key is missing", async () => {
  const client = fakeClient(async () => ({ data: { "other": { status: "connected" } } }));
  const status = await getForgeMcpStatus(client, "forge-alpha");
  assert.equal(status, undefined);
});

test("getForgeMcpStatus returns undefined when data is missing", async () => {
  const client = fakeClient(async () => ({}));
  const status = await getForgeMcpStatus(client, "forge-alpha");
  assert.equal(status, undefined);
});

test("getForgeMcpStatus returns undefined when status() rejects", async () => {
  const client = fakeClient(async () => { throw new Error("network"); });
  const status = await getForgeMcpStatus(client, "forge-alpha");
  assert.equal(status, undefined);
});

test("getForgeMcpStatus returns undefined when result is undefined", async () => {
  const client = fakeClient(async () => undefined);
  const status = await getForgeMcpStatus(client, "forge-alpha");
  assert.equal(status, undefined);
});

// ---------------------------------------------------------------------------
// waitForForgeMcpConnected unit tests
// ---------------------------------------------------------------------------

test("waitForForgeMcpConnected returns true immediately when connected", async () => {
  const client = fakeClient(async () => connectedResult());
  const start = Date.now();
  const ok = await waitForForgeMcpConnected(client, "forge-alpha", 3000);
  assert.equal(ok, true);
  assert.ok(Date.now() - start < 200, "should not poll when already connected");
});

test("waitForForgeMcpConnected short-circuits on disabled", async () => {
  const client = fakeClient(async () => ({ data: { "forge-alpha": { status: "disabled" } } }));
  const start = Date.now();
  const ok = await waitForForgeMcpConnected(client, "forge-alpha", 3000);
  assert.equal(ok, false);
  assert.ok(Date.now() - start < 200, "disabled should short-circuit without waiting");
});

test("waitForForgeMcpConnected short-circuits on failed", async () => {
  const client = fakeClient(async () => ({ data: { "forge-alpha": { status: "failed", error: "x" } } }));
  const ok = await waitForForgeMcpConnected(client, "forge-alpha", 3000);
  assert.equal(ok, false);
});

test("waitForForgeMcpConnected short-circuits on needs_auth", async () => {
  const client = fakeClient(async () => ({ data: { "forge-alpha": { status: "needs_auth" } } }));
  const ok = await waitForForgeMcpConnected(client, "forge-alpha", 3000);
  assert.equal(ok, false);
});

test("waitForForgeMcpConnected short-circuits on needs_client_registration", async () => {
  const client = fakeClient(async () => ({ data: { "forge-alpha": { status: "needs_client_registration", error: "x" } } }));
  const ok = await waitForForgeMcpConnected(client, "forge-alpha", 3000);
  assert.equal(ok, false);
});

test("waitForForgeMcpConnected polls then succeeds when status becomes connected", async () => {
  let calls = 0;
  const client = fakeClient(async () => {
    calls++;
    // Cold start: key absent from map (undefined -> non-terminal -> polls), then connected.
    if (calls < 3) return { data: {} };
    return connectedResult();
  });
  const ok = await waitForForgeMcpConnected(client, "forge-alpha", 5000);
  assert.equal(ok, true);
  assert.ok(calls >= 3, `should have polled at least 3 times, got ${calls}`);
});

test("waitForForgeMcpConnected returns false on timeout with unknown status", async () => {
  const client = fakeClient(async () => undefined);
  const ok = await waitForForgeMcpConnected(client, "forge-alpha", 50);
  assert.equal(ok, false);
});

test("waitForForgeMcpConnected returns false on timeout when key always missing", async () => {
  const client = fakeClient(async () => ({ data: { "other": { status: "connected" } } }));
  const ok = await waitForForgeMcpConnected(client, "forge-alpha", 50);
  assert.equal(ok, false);
});

// ---------------------------------------------------------------------------
// Hook integration tests via ForgeAlphaPlugin
// ---------------------------------------------------------------------------

async function setupPlugin(
  statusFn: () => Promise<unknown>,
  options?: Record<string, unknown>,
) {
  const root = tmpDir();
  const client = fakeClient(statusFn);
  const hooks = await ForgeAlphaPlugin(
    { worktree: root, directory: root, client } as never,
    // Default a 50ms readiness deadline for tests so timeout cases are fast.
    { forgeMcpReadinessMs: 50, ...options } as never,
  );
  return { root, hooks, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

test("T1: hook injects into system[0] when MCP connected (no new element)", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => connectedResult());
  try {
    const output = { system: ["base prompt"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.equal(output.system.length, 1, "must not push a new element");
    assert.ok(output.system[0].startsWith("base prompt"), "base prompt must remain at start");
    assert.ok(output.system[0].includes(FORGE_SYSTEM_MARKER_OPEN));
    assert.ok(output.system[0].includes(FORGE_SYSTEM_MARKER_CLOSE));
    assert.ok(output.system[0].includes(FORGE_SYSTEM_BOOTSTRAP));
  } finally {
    cleanup();
  }
});

test("T2: no injection when MCP disabled", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => ({ data: { "forge-alpha": { status: "disabled" } } }));
  try {
    const output = { system: ["base prompt"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.equal(output.system[0], "base prompt");
    assert.ok(!output.system[0].includes(FORGE_SYSTEM_MARKER_OPEN));
  } finally {
    cleanup();
  }
});

test("T3: no injection when MCP failed", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => ({ data: { "forge-alpha": { status: "failed", error: "x" } } }));
  try {
    const output = { system: ["base prompt"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.equal(output.system[0], "base prompt");
  } finally {
    cleanup();
  }
});

test("T4: no injection when MCP needs_auth", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => ({ data: { "forge-alpha": { status: "needs_auth" } } }));
  try {
    const output = { system: ["base prompt"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.equal(output.system[0], "base prompt");
  } finally {
    cleanup();
  }
});

test("T5: no injection when forge-alpha key missing from servers", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => ({ data: { "other": { status: "connected" } } }));
  try {
    const output = { system: ["base prompt"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.equal(output.system[0], "base prompt");
  } finally {
    cleanup();
  }
});

test("T6: no injection when data field missing from result", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => ({}));
  try {
    const output = { system: ["base prompt"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.equal(output.system[0], "base prompt");
  } finally {
    cleanup();
  }
});

test("T6b: no injection when status() resolves to undefined", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => undefined);
  try {
    const output = { system: ["base prompt"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.equal(output.system[0], "base prompt");
  } finally {
    cleanup();
  }
});

test("T7: no injection and no throw when status() rejects", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => { throw new Error("network"); });
  try {
    const output = { system: ["base prompt"] };
    await assert.doesNotReject(
      hooks["experimental.chat.system.transform"]!({} as never, output as never),
    );
    assert.equal(output.system[0], "base prompt");
  } finally {
    cleanup();
  }
});

test("T8: no throw and no mutation when system is malformed", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => connectedResult());
  try {
    // empty array
    const empty = { system: [] };
    await assert.doesNotReject(hooks["experimental.chat.system.transform"]!({} as never, empty as never));
    assert.deepEqual(empty.system, []);

    // non-string first element
    const nonString = { system: [123] };
    await assert.doesNotReject(hooks["experimental.chat.system.transform"]!({} as never, nonString as never));
    assert.equal(nonString.system[0], 123);

    // system is not an array
    const notArray = { system: "just a string" };
    await assert.doesNotReject(hooks["experimental.chat.system.transform"]!({} as never, notArray as never));
    assert.equal(notArray.system, "just a string");
  } finally {
    cleanup();
  }
});

test("T9: no duplicate injection when marker already present", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => connectedResult());
  try {
    const alreadyInjected = { system: [`base prompt\n\n${forgeSystemBlock()}`] };
    const original = alreadyInjected.system[0];
    await hooks["experimental.chat.system.transform"]!({} as never, alreadyInjected as never);
    assert.equal(alreadyInjected.system[0], original, "must be idempotent");
    assert.equal(alreadyInjected.system.length, 1);
  } finally {
    cleanup();
  }
});

test("T10: custom forgeMcpKey via plugin options", async () => {
  const { hooks, cleanup } = await setupPlugin(
    async () => ({ data: { "custom-forge": { status: "connected" } } }),
    { forgeMcpKey: "custom-forge" },
  );
  try {
    const output = { system: ["base"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.ok(output.system[0].includes(FORGE_SYSTEM_MARKER_OPEN), "custom key should trigger injection");
  } finally {
    cleanup();
  }
});

test("T10b: default key does not match when custom key configured", async () => {
  const { hooks, cleanup } = await setupPlugin(
    async () => ({ data: { "forge-alpha": { status: "connected" } } }),
    { forgeMcpKey: "custom-forge" },
  );
  try {
    const output = { system: ["base"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.equal(output.system[0], "base", "should not inject under wrong key");
  } finally {
    cleanup();
  }
});

test("T11: FORGE_MCP_KEY env var overrides default key", async () => {
  const prev = process.env.FORGE_MCP_KEY;
  process.env.FORGE_MCP_KEY = "env-forge";
  try {
    const { hooks, cleanup } = await setupPlugin(
      async () => ({ data: { "env-forge": { status: "connected" } } }),
    );
    try {
      const output = { system: ["base"] };
      await hooks["experimental.chat.system.transform"]!({} as never, output as never);
      assert.ok(output.system[0].includes(FORGE_SYSTEM_MARKER_OPEN));
    } finally {
      cleanup();
    }
  } finally {
    if (prev === undefined) delete process.env.FORGE_MCP_KEY;
    else process.env.FORGE_MCP_KEY = prev;
  }
});

test("T12: hook does not call any client method other than mcp.status", async () => {
  const root = tmpDir();
  let statusCalls = 0;
  const client = new Proxy({
    mcp: {
      status: async () => { statusCalls++; return connectedResult(); },
    },
    tui: { showToast: async () => undefined },
  } as Record<string, unknown>, {
    get(target, prop) {
      if (prop === "mcp" || prop === "tui" || prop === "then") return target[prop as string];
      assert.fail(`hook must not access client.${String(prop)}`);
    },
  });
  try {
    const hooks = await ForgeAlphaPlugin(
      { worktree: root, directory: root, client } as never,
    );
    const output = { system: ["base"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.ok(statusCalls > 0, "mcp.status must have been called");
    assert.ok(output.system[0].includes(FORGE_SYSTEM_MARKER_OPEN));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("T13: marker and bootstrap constants are locked", () => {
  assert.equal(FORGE_SYSTEM_MARKER_OPEN, "<forge_system>");
  assert.equal(FORGE_SYSTEM_MARKER_CLOSE, "</forge_system>");
  // Placeholder must be a non-empty real protocol, not a placeholder string.
  assert.ok(!FORGE_SYSTEM_BOOTSTRAP.includes("PLACEHOLDER"));
  assert.ok(FORGE_SYSTEM_BOOTSTRAP.startsWith("# Forge Native Operating Protocol"));
});

test("T14: readiness wait converts intermediate status to connected", async () => {
  let calls = 0;
  const { hooks, cleanup } = await setupPlugin(
    async () => {
      calls++;
      // Cold start: server not yet in the status map (undefined -> non-terminal -> polls).
      if (calls < 2) return { data: {} };
      return connectedResult();
    },
    { forgeMcpReadinessMs: 500 },
  );
  try {
    const output = { system: ["base"] };
    await hooks["experimental.chat.system.transform"]!({} as never, output as never);
    assert.ok(output.system[0].includes(FORGE_SYSTEM_MARKER_OPEN), "should inject after readiness wait");
    assert.ok(calls >= 2, `should have polled at least twice, got ${calls}`);
  } finally {
    cleanup();
  }
});

test("T17: hook injects even without sessionID (Agent.generate path)", async () => {
  const { hooks, cleanup } = await setupPlugin(async () => connectedResult());
  try {
    const output = { system: ["base"] };
    // Agent.generate path passes only { model }, no sessionID.
    await hooks["experimental.chat.system.transform"]!({ model: {} } as never, output as never);
    assert.ok(output.system[0].includes(FORGE_SYSTEM_MARKER_OPEN));
  } finally {
    cleanup();
  }
});
