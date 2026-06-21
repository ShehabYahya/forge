import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("adapter remains transport-only", async () => {
  const source = await readFile("src/index.ts", "utf8");
  assert.match(source, /observe_tool_before/);
  assert.match(source, /backend unavailable/);
  assert.doesNotMatch(source, /transition|dangerous|duplicate/i);
});

