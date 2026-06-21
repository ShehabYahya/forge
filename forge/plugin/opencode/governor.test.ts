import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import {
  ContextGovernor,
  estimateTokens,
  fingerprint,
} from "./src/governor.ts";

function tmpDir(): string {
  const dir = join(tmpdir(), "forge-test-" + randomBytes(8).toString("hex"));
  mkdirSync(dir, { recursive: true });
  return dir;
}

test("estimateTokens boundaries", () => {
  assert.equal(estimateTokens(""), 0);
  assert.equal(estimateTokens("a"), 1);
  assert.equal(estimateTokens("abcd"), 1);
  assert.equal(estimateTokens("abcde"), 2);
});

test("fingerprint is stable across field order", () => {
  assert.equal(
    fingerprint("bash", { b: 2, a: 1 }),
    fingerprint("bash", { a: 1, b: 2 }),
  );
  assert.notEqual(
    fingerprint("bash", { a: 1 }),
    fingerprint("bash", { a: 2 }),
  );
});

test("fingerprint is stable across case normalization", () => {
  const fp = fingerprint("Shell", { b: 2, a: 1 });
  assert.equal(fp.length, 64);
  const fpLower = fingerprint("shell", { a: 1, b: 2 });
  assert.equal(fp, fpLower);
});

test("duplicate modes and window", () => {
  const runtime = tmpDir();
  let t = 0;
  const clock = { now: () => { const v = t; t += 1; return v; } };
  const origNow = Date.now;
  try {
    Date.now = () => clock.now() * 1000;
    const governor = new ContextGovernor("active", "/tmp/repo", {
      can_block_before: true,
    }, runtime);
    assert.equal(governor.before("s", "read", { path: "base.txt" }).decision, "allow");
    assert.equal(governor.before("s", "read", { path: "base.txt" }).decision, "block");
    Date.now = () => 100 * 1000;
    assert.equal(governor.before("s", "read", { path: "base.txt" }).decision, "allow");
  } finally {
    Date.now = origNow;
    rmSync(runtime, { recursive: true, force: true });
  }
});

test("dangerous command escalates with capability, warns without", () => {
  const runtime = tmpDir();
  try {
    const limited = new ContextGovernor("active", "/tmp/repo", {}, runtime);
    const r1 = limited.before("s", "bash", { command: "rm -rf build" });
    assert.equal(r1.decision, "warn");
    assert.equal(r1.capability_limited, true);

    const capable = new ContextGovernor("active", "/tmp/repo", {
      can_request_confirmation: true,
    }, runtime);
    const r2 = capable.before("s", "bash", { command: "rm -rf build" });
    assert.equal(r2.decision, "escalate");
    assert.equal(capable.before("s", "bash", { command: "ls build" }).decision, "allow");
  } finally {
    rmSync(runtime, { recursive: true, force: true });
  }
});

test("out-of-repo path and large output capabilities", () => {
  const runtime = tmpDir();
  try {
    const governor = new ContextGovernor("report", "/tmp/repo", {}, runtime);
    assert.equal(governor.before("s", "write", { path: "../outside" }).decision, "warn");
    assert.equal(governor.after("s", "bash", "x".repeat(8001)).decision, "warn");

    const active = new ContextGovernor("active", "/tmp/repo", {
      can_replace_output: true,
    }, runtime);
    const result = active.after("s", "bash", "x".repeat(8001));
    assert.equal(result.decision, "replace");
    assert.ok(result.replacement_output?.startsWith("Large output stored as fr_"));
  } finally {
    rmSync(runtime, { recursive: true, force: true });
  }
});

test("off mode allows dangerous input", () => {
  const runtime = tmpDir();
  try {
    const governor = new ContextGovernor("off", "/tmp/repo", {}, runtime);
    assert.equal(governor.before("s", "bash", { command: "rm -rf /" }).decision, "allow");
  } finally {
    rmSync(runtime, { recursive: true, force: true });
  }
});

test("large output warns when can_replace_output is false", () => {
  const runtime = tmpDir();
  try {
    const governor = new ContextGovernor("active", "/tmp/repo", {
      can_replace_output: false,
    }, runtime);
    const result = governor.after("s", "bash", "x".repeat(8001));
    assert.equal(result.decision, "warn");
    assert.equal(result.capability_limited, true);
  } finally {
    rmSync(runtime, { recursive: true, force: true });
  }
});

test("invalid mode throws", () => {
  assert.throws(() => new ContextGovernor("borked", "/tmp/repo"));
});
