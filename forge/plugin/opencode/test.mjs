import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("adapter remains transport-only", async () => {
  const source = await readFile("src/index.ts", "utf8");
  assert.match(source, /ContextGovernor/);
  assert.doesNotMatch(source, /transition|dangerous|duplicate|anvil stage/i);
});

test("governor module contains policy logic", async () => {
  const source = await readFile("src/governor.ts", "utf8");
  assert.match(source, /DANGEROUS/);
  assert.match(source, /fingerprint/);
  assert.match(source, /unsafePaths/);
});
