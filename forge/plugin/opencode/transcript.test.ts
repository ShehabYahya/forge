import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, symlinkSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { TranscriptDigester } from "./src/transcript.ts";

test("after records edit file paths", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  d.after("s1", "edit", { filePath: "/repo/b.ts" }, "");
  const digest = d.flush("s1");
  assert.deepEqual(digest.edited_files, ["/repo/a.ts", "/repo/b.ts"]);
});

test("after records write file paths via filePath", () => {
  const d = new TranscriptDigester();
  d.after("s1", "write", { filePath: "/repo/c.py" }, "");
  const digest = d.flush("s1");
  assert.deepEqual(digest.edited_files, ["/repo/c.py"]);
});

test("after deduplicates edited files across multiple calls", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  d.after("s1", "write", { filePath: "/repo/a.ts" }, "");
  const digest = d.flush("s1");
  assert.deepEqual(digest.edited_files, ["/repo/a.ts"]);
});

test("after ignores edit/write without filePath", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", {}, "");
  d.after("s1", "write", {}, "");
  const digest = d.flush("s1");
  assert.deepEqual(digest.edited_files, []);
});

test("after records test command output", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "pytest tests/" }, "10 passed\n");
  const digest = d.flush("s1");
  assert.equal(digest.test_runs.length, 1);
  assert.equal(digest.test_runs[0].command, "pytest tests/");
  assert.equal(digest.test_runs[0].output, "10 passed\n");
});

test("after records npm test as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "npm test" }, "all good\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("after ignores non-test bash commands", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "ls -la" }, "file list\n");
  d.after("s1", "bash", { command: "echo hello" }, "hello\n");
  assert.equal(d.flush("s1").test_runs.length, 0);
});

test("after ignores bash without command string", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", {}, "");
  d.after("s1", "bash", { command: "" }, "");
  assert.equal(d.flush("s1").test_runs.length, 0);
});

test("after caps test output at 16000 characters", () => {
  const d = new TranscriptDigester();
  const long = "x".repeat(20_000);
  d.after("s1", "bash", { command: "pytest" }, long);
  const output = d.flush("s1").test_runs[0].output;
  assert.equal(output.length, 16_000);
});

test("after wraps errors silently (never throws)", () => {
  const d = new TranscriptDigester();
  // Simulate a broken call that would normally throw
  assert.doesNotThrow(() => {
    d.after("s1", "edit", null as unknown as Record<string, unknown>, "");
  });
  assert.doesNotThrow(() => {
    d.after("s1", "bash", null as unknown as Record<string, unknown>, "");
  });
});

test("flush returns cumulative snapshot (non-destructive)", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  d.after("s1", "bash", { command: "pytest" }, "ok\n");
  const first = d.flush("s1");
  assert.equal(first.edited_files.length, 1);
  assert.equal(first.test_runs.length, 1);
  // Second flush returns same cumulative data
  d.after("s1", "edit", { filePath: "/repo/b.ts" }, "");
  const second = d.flush("s1");
  assert.equal(second.edited_files.length, 2);
  assert.equal(second.test_runs.length, 1);
});

test("flush computes edited_files_digest as SHA256 over the edit sequence", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", { filePath: "/repo/b.ts" }, "");
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  const digest = d.flush("s1");
  assert.equal(typeof digest.edited_files_digest, "string");
  assert.equal(digest.edited_files_digest.length, 64); // SHA256 hex
  // Same sequence produces the same digest.
  const d2 = new TranscriptDigester();
  d2.after("s2", "edit", { filePath: "/repo/b.ts" }, "");
  d2.after("s2", "edit", { filePath: "/repo/a.ts" }, "");
  assert.equal(digest.edited_files_digest, d2.flush("s2").edited_files_digest);
});

test("flush digest changes when the same file is edited again", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  const first = d.flush("s1").edited_files_digest;
  d.after("s1", "write", { filePath: "/repo/a.ts" }, "");
  const second = d.flush("s1").edited_files_digest;
  assert.notEqual(first, second);
});

test("flush handles unknown session gracefully", () => {
  const d = new TranscriptDigester();
  const digest = d.flush("nonexistent");
  assert.deepEqual(digest.edited_files, []);
  assert.equal(typeof digest.edited_files_digest, "string");
  assert.deepEqual(digest.test_runs, []);
});

test("clear frees accumulated evidence", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  d.after("s1", "bash", { command: "pytest" }, "ok\n");
  d.clear("s1");
  assert.deepEqual(d.flush("s1").edited_files, []);
  assert.deepEqual(d.flush("s1").test_runs, []);
});

test("sessions are isolated from each other", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  d.after("s2", "edit", { filePath: "/repo/b.ts" }, "");
  assert.deepEqual(d.flush("s1").edited_files, ["/repo/a.ts"]);
  assert.deepEqual(d.flush("s2").edited_files, ["/repo/b.ts"]);
});

test("node --test is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "node --test transcript.test.ts" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("cargo test is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "cargo test" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("flush returns a shallow copy of test_runs", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "pytest" }, "output1\n");
  const digest1 = d.flush("s1");
  const len1 = digest1.test_runs.length;
  d.after("s1", "bash", { command: "cargo test" }, "output2\n");
  assert.equal(digest1.test_runs.length, len1);
  const digest2 = d.flush("s1");
  assert.equal(digest2.test_runs.length, 2);
});

test("rake test is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "rake test" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("mvn test is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "mvn test" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("gradle test is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "gradle test" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("dotnet test is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "dotnet test" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("jest is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "jest" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("vitest is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "vitest run" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("bun test is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "bun test" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("deno test is recognized as test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "deno test" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

test("python script.py unittest is NOT a test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "python script.py unittest" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 0);
});

test("python -m unittest IS a test command", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "python -m unittest" }, "ok\n");
  assert.equal(d.flush("s1").test_runs.length, 1);
});

// -------------------------------------------------- content-aware digest (v2)

function makeWorktree(): string {
  const dir = mkdtempSync(join(tmpdir(), "forge-test-"));
  return dir;
}

test("content-aware digest: same path different content produces different digest", () => {
  const wt = makeWorktree();
  try {
    writeFileSync(join(wt, "a.ts"), "content v1\n");
    const d = new TranscriptDigester(wt);
    d.after("s1", "edit", { filePath: join(wt, "a.ts") }, "");
    const digest1 = d.flush("s1");
    assert.equal(digest1.digest_version, 2);
    writeFileSync(join(wt, "a.ts"), "content v2\n");
    const digest2 = d.flush("s1");
    assert.equal(digest2.digest_version, 2);
    assert.notEqual(digest1.edited_files_digest, digest2.edited_files_digest);
  } finally {
    rmSync(wt, { recursive: true, force: true });
  }
});

test("content-aware digest: same content produces same digest", () => {
  const wt = makeWorktree();
  try {
    writeFileSync(join(wt, "a.ts"), "same content\n");
    const d1 = new TranscriptDigester(wt);
    d1.after("s1", "edit", { filePath: join(wt, "a.ts") }, "");
    const d2 = new TranscriptDigester(wt);
    d2.after("s2", "edit", { filePath: join(wt, "a.ts") }, "");
    assert.equal(d1.flush("s1").edited_files_digest, d2.flush("s2").edited_files_digest);
  } finally {
    rmSync(wt, { recursive: true, force: true });
  }
});

test("content-aware digest: absolute and relative paths normalize consistently", () => {
  const wt = makeWorktree();
  try {
    mkdirSync(join(wt, "src"), { recursive: true });
    writeFileSync(join(wt, "src", "a.ts"), "content\n");
    const dAbs = new TranscriptDigester(wt);
    dAbs.after("s1", "edit", { filePath: join(wt, "src", "a.ts") }, "");
    const absDigest = dAbs.flush("s1");
    const dRel = new TranscriptDigester(wt);
    dRel.after("s2", "edit", { filePath: "src/a.ts" }, "");
    const relDigest = dRel.flush("s2");
    assert.equal(absDigest.edited_files_digest, relDigest.edited_files_digest);
    assert.deepEqual(absDigest.edited_files, ["src/a.ts"]);
    assert.deepEqual(relDigest.edited_files, ["src/a.ts"]);
  } finally {
    rmSync(wt, { recursive: true, force: true });
  }
});

test("content-aware digest: relative path content changes digest", () => {
  const wt = makeWorktree();
  try {
    writeFileSync(join(wt, "a.ts"), "content v1\n");
    const d = new TranscriptDigester(wt);
    d.after("s1", "edit", { filePath: "a.ts" }, "");
    const digest1 = d.flush("s1");
    writeFileSync(join(wt, "a.ts"), "content v2\n");
    const digest2 = d.flush("s1");
    assert.notEqual(digest1.edited_files_digest, digest2.edited_files_digest);
  } finally {
    rmSync(wt, { recursive: true, force: true });
  }
});

test("content-aware digest: same-file edit after review changes digest even if content is restored", () => {
  const wt = makeWorktree();
  try {
    writeFileSync(join(wt, "a.ts"), "content v1\n");
    const d = new TranscriptDigester(wt);
    d.after("s1", "edit", { filePath: join(wt, "a.ts") }, "");
    const reviewed = d.flush("s1");
    writeFileSync(join(wt, "a.ts"), "content v2\n");
    d.after("s1", "write", { filePath: join(wt, "a.ts") }, "");
    writeFileSync(join(wt, "a.ts"), "content v1\n");
    const finish = d.flush("s1");
    assert.notEqual(reviewed.edited_files_digest, finish.edited_files_digest);
  } finally {
    rmSync(wt, { recursive: true, force: true });
  }
});

test("content-aware digest: missing file state changes digest", () => {
  const wt = makeWorktree();
  try {
    writeFileSync(join(wt, "a.ts"), "content\n");
    const d = new TranscriptDigester(wt);
    d.after("s1", "edit", { filePath: join(wt, "a.ts") }, "");
    const digestWithFile = d.flush("s1");
    rmSync(join(wt, "a.ts"));
    const digestMissing = d.flush("s1");
    assert.notEqual(digestWithFile.edited_files_digest, digestMissing.edited_files_digest);
  } finally {
    rmSync(wt, { recursive: true, force: true });
  }
});

test("content-aware digest: symlink is never followed", () => {
  const wt = makeWorktree();
  try {
    writeFileSync(join(wt, "target.ts"), "target content\n");
    symlinkSync("target.ts", join(wt, "link.ts"));
    const d = new TranscriptDigester(wt);
    d.after("s1", "edit", { filePath: join(wt, "link.ts") }, "");
    const digest = d.flush("s1");
    assert.equal(digest.digest_version, 2);
    assert.equal(typeof digest.edited_files_digest, "string");
    assert.equal(digest.edited_files_digest.length, 64);
  } finally {
    rmSync(wt, { recursive: true, force: true });
  }
});

test("content-aware digest: unreadable file does not crash flush", () => {
  const wt = makeWorktree();
  try {
    writeFileSync(join(wt, "secret.ts"), "secret\n");
    chmodSync(join(wt, "secret.ts"), 0o000);
    const d = new TranscriptDigester(wt);
    d.after("s1", "edit", { filePath: join(wt, "secret.ts") }, "");
    assert.doesNotThrow(() => d.flush("s1"));
    const digest = d.flush("s1");
    assert.equal(digest.digest_version, 2);
    assert.equal(typeof digest.edited_files_digest, "string");
  } finally {
    rmSync(wt, { recursive: true, force: true });
  }
});

test("content-aware digest: path outside worktree is marked unreadable", () => {
  const wt = makeWorktree();
  const outside = mkdtempSync(join(tmpdir(), "forge-out-"));
  try {
    writeFileSync(join(outside, "ext.ts"), "external\n");
    writeFileSync(join(wt, "a.ts"), "content\n");
    const d = new TranscriptDigester(wt);
    d.after("s1", "edit", { filePath: join(wt, "a.ts") }, "");
    d.after("s1", "edit", { filePath: join(outside, "ext.ts") }, "");
    assert.doesNotThrow(() => d.flush("s1"));
    const digest = d.flush("s1");
    assert.equal(digest.digest_version, 2);
  } finally {
    rmSync(wt, { recursive: true, force: true });
    rmSync(outside, { recursive: true, force: true });
  }
});

test("no-worktree digester produces digest_version 1", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  const digest = d.flush("s1");
  assert.equal(digest.digest_version, 1);
});

test("unrelated file not in edited_files does not change digest", () => {
  const wt = makeWorktree();
  try {
    writeFileSync(join(wt, "a.ts"), "content A\n");
    writeFileSync(join(wt, "b.ts"), "content B\n");
    const d = new TranscriptDigester(wt);
    d.after("s1", "edit", { filePath: join(wt, "a.ts") }, "");
    const digest1 = d.flush("s1");
    writeFileSync(join(wt, "b.ts"), "content B modified\n");
    const digest2 = d.flush("s1");
    assert.equal(digest1.edited_files_digest, digest2.edited_files_digest);
  } finally {
    rmSync(wt, { recursive: true, force: true });
  }
});

// -------------------------------------------------- exit_code capture (Issue 4)

test("after captures exit_code from metadata exitCode field", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "pytest" }, "3 passed\n", { exitCode: 0 });
  const run = d.flush("s1").test_runs[0];
  assert.equal(run.exit_code, 0);
});

test("after captures exit_code from metadata exit_code field", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "pytest" }, "1 failed\n", { exit_code: 1 });
  const run = d.flush("s1").test_runs[0];
  assert.equal(run.exit_code, 1);
});

test("after captures exit_code from metadata code field", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "pytest" }, "error\n", { code: 2 });
  const run = d.flush("s1").test_runs[0];
  assert.equal(run.exit_code, 2);
});

test("after stores null exit_code when metadata absent", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "pytest" }, "3 passed\n");
  const run = d.flush("s1").test_runs[0];
  assert.equal(run.exit_code, null);
});

test("after stores null exit_code when metadata has no exit code keys", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "pytest" }, "3 passed\n", { truncated: false });
  const run = d.flush("s1").test_runs[0];
  assert.equal(run.exit_code, null);
});

test("after stores null exit_code for non-integer exit code", () => {
  const d = new TranscriptDigester();
  d.after("s1", "bash", { command: "pytest" }, "3 passed\n", { exitCode: "0" });
  const run = d.flush("s1").test_runs[0];
  assert.equal(run.exit_code, null);
});
