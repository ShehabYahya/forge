import test from "node:test";
import assert from "node:assert/strict";
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

test("flush computes edited_files_digest as SHA256 over sorted paths", () => {
  const d = new TranscriptDigester();
  d.after("s1", "edit", { filePath: "/repo/b.ts" }, "");
  d.after("s1", "edit", { filePath: "/repo/a.ts" }, "");
  const digest = d.flush("s1");
  assert.equal(typeof digest.edited_files_digest, "string");
  assert.equal(digest.edited_files_digest.length, 64); // SHA256 hex
  // Same files produce same digest regardless of insertion order
  const d2 = new TranscriptDigester();
  d2.after("s2", "edit", { filePath: "/repo/b.ts" }, "");
  d2.after("s2", "edit", { filePath: "/repo/a.ts" }, "");
  assert.equal(digest.edited_files_digest, d2.flush("s2").edited_files_digest);
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
