import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import {
  ContextGovernor,
  dangerousCommandReason,
  fingerprint,
} from "./src/governor.ts";

function tmpDir(): string {
  const dir = join(tmpdir(), "forge-governor-test-" + randomBytes(8).toString("hex"));
  mkdirSync(dir, { recursive: true });
  return dir;
}

test("fingerprint is stable for recursively reordered objects", () => {
  assert.equal(
    fingerprint("Shell", { nested: { b: 2, a: 1 }, z: 3 }),
    fingerprint("shell", { z: 3, nested: { a: 1, b: 2 } }),
  );
});

test("duplicate reads are blocked only inside the same session", () => {
  const repo = tmpDir();
  try {
    const governor = new ContextGovernor("active", repo, { can_block_before: true });
    assert.equal(governor.before("session-a", "read", { filePath: "base.txt" }).decision, "allow");
    assert.equal(governor.before("session-b", "read", { filePath: "base.txt" }).decision, "allow");
    assert.equal(governor.before("session-a", "read", { filePath: "base.txt" }).decision, "block");
    assert.equal(governor.before("session-a", "bash", { command: "pwd" }).decision, "allow");
    assert.equal(governor.before("session-a", "bash", { command: "pwd" }).decision, "allow");
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("clearing a session removes only its duplicate history", () => {
  const repo = tmpDir();
  try {
    const governor = new ContextGovernor("active", repo, { can_block_before: true });
    governor.before("session-a", "read", { path: "x" });
    governor.before("session-b", "read", { path: "x" });
    governor.clearSession("session-a");
    assert.equal(governor.before("session-a", "read", { path: "x" }).decision, "allow");
    assert.equal(governor.before("session-b", "read", { path: "x" }).decision, "block");
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("dangerous command variants escalate instead of blocking", () => {
  const repo = tmpDir();
  try {
    const governor = new ContextGovernor("active", repo, { can_request_confirmation: true });
    for (const command of [
      "rm -rf build",
      "rm -r -f build",
      "rm --recursive --force build",
      "git reset --hard",
      "git -C . reset --hard",
      "git push origin main --force-with-lease",
      "sudo apt update",
      "dd if=/dev/zero of=disk.img",
    ]) {
      assert.ok(dangerousCommandReason(command), command);
      assert.equal(governor.before("session", "bash", { command }).decision, "escalate", command);
    }
    assert.equal(governor.before("session", "bash", { command: "git status" }).decision, "allow");
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("filePath and symlinked nonexistent children escalate outside the repo", () => {
  const root = tmpDir();
  const repo = join(root, "repo");
  const outside = join(root, "outside");
  mkdirSync(repo);
  mkdirSync(outside);
  symlinkSync(outside, join(repo, "linked"));
  try {
    const governor = new ContextGovernor("active", repo, { can_request_confirmation: true });
    assert.equal(
      governor.before("session", "read", { filePath: join(outside, "secret.txt") }).decision,
      "escalate",
    );
    assert.equal(
      governor.before("session", "write", { filePath: join(repo, "linked", "new.txt") }).decision,
      "escalate",
    );
    assert.equal(
      governor.before("session", "read", { filePath: join(repo, "inside.txt") }).decision,
      "allow",
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("report and off modes do not enforce", () => {
  const repo = tmpDir();
  try {
    const report = new ContextGovernor("report", repo, { can_request_confirmation: true });
    assert.equal(report.before("session", "bash", { command: "rm -rf build" }).decision, "warn");
    const off = new ContextGovernor("off", repo, { can_request_confirmation: true });
    assert.equal(off.before("session", "bash", { command: "rm -rf build" }).decision, "allow");
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("invalid mode throws", () => {
  assert.throws(() => new ContextGovernor("invalid", "/tmp"));
});
