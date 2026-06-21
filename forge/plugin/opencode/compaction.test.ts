import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { ToolOutputCompactor } from "./src/compaction.ts";

function tmpDir(): string {
  const dir = join(tmpdir(), "forge-compaction-test-" + randomBytes(8).toString("hex"));
  mkdirSync(dir, { recursive: true });
  return dir;
}

test("compaction summarizes exact line ranges and expands them without cumulative rationing", async () => {
  const root = tmpDir();
  try {
    const content = Array.from({ length: 120 }, (_, index) => {
      if (index === 49) return "ERROR target failure at line 50";
      return `source line ${index + 1}`;
    }).join("\n");
    const compactor = new ToolOutputCompactor(root, 100, 8, 40, 64_000);
    const compacted = await compactor.compact("session-a", "bash", content);
    assert.ok(compacted);
    assert.match(compacted.replacement_output, /L1-L\d+:/);
    assert.match(compacted.replacement_output, /error signal/i);
    assert.match(compacted.replacement_output, /forge_expand_output/);

    const first = await compactor.expand("session-a", compacted.handle, 48, 52);
    const second = await compactor.expand("session-a", compacted.handle, 48, 52);
    assert.equal(first.content, second.content);
    assert.match(first.content, /ERROR target failure at line 50/);
    assert.equal(first.start_line, 48);
    assert.equal(first.end_line, 52);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("search returns line-addressed context without reading the full output", async () => {
  const root = tmpDir();
  try {
    const content = Array.from({ length: 80 }, (_, index) => `line ${index + 1}`).join("\n")
      .replace("line 37", "line 37 unique-needle");
    const compactor = new ToolOutputCompactor(root, 10);
    const compacted = await compactor.compact("session-a", "read", content);
    assert.ok(compacted);
    const result = await compactor.search("session-a", compacted.handle, "unique-needle", 1);
    assert.equal(result.total_matches, 1);
    assert.deepEqual(
      [result.matches[0].start_line, result.matches[0].end_line],
      [36, 38],
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("search expansion enforces the same character cap as line expansion", async () => {
  const root = tmpDir();
  try {
    const compactor = new ToolOutputCompactor(root, 10, 20, 240, 100);
    const compacted = await compactor.compact(
      "session-a",
      "read",
      `needle ${"x".repeat(500)}\nneedle again`,
    );
    assert.ok(compacted);
    const result = await compactor.search("session-a", compacted.handle, "needle", 0);
    assert.equal(result.total_matches, 2);
    assert.equal(result.matches.length, 1);
    assert.equal(result.matches[0].content.length, 100);
    assert.equal(result.truncated, true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("stored output is session-owned, integrity checked, and redacted", async () => {
  const root = tmpDir();
  try {
    const compactor = new ToolOutputCompactor(root, 10);
    const compacted = await compactor.compact(
      "session-a",
      "read",
      "api_key=supersecret\n" + "x".repeat(100),
    );
    assert.ok(compacted);
    assert.doesNotMatch(readFileSync(join(root, `${compacted.handle}.raw`), "utf8"), /supersecret/);
    await assert.rejects(
      compactor.expand("session-b", compacted.handle),
      /another session/,
    );
    await assert.rejects(
      compactor.expand("session-a", "../escape"),
      /malformed/,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("small output remains untouched", async () => {
  const root = tmpDir();
  try {
    const compactor = new ToolOutputCompactor(root, 100);
    assert.equal(await compactor.compact("session", "read", "small"), null);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
