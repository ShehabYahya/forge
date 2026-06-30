import test from "node:test";
import assert from "node:assert/strict";
import { mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { mkdirSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { unsafePaths } from "./src/governor.ts";

const fixturePath = join(dirname(fileURLToPath(import.meta.url)), "path_safety_cases.json");
const fixture = JSON.parse(await readFile(fixturePath, "utf8")) as Array<Record<string, unknown>>;
const cases = fixture.slice(1);

const IS_WIN32 = process.platform === "win32";

function tmpDir(): string {
  const dir = join(tmpdir(), "forge-path-safety-" + randomBytes(8).toString("hex"));
  mkdirSync(dir, { recursive: true });
  return dir;
}

function substitute(value: unknown, mapping: Record<string, string>): unknown {
  if (typeof value === "string") {
    let result = value;
    for (const [placeholder, real] of Object.entries(mapping)) {
      result = result.split(placeholder).join(real);
    }
    return result;
  }
  if (Array.isArray(value)) return value.map((v) => substitute(v, mapping));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, substitute(v, mapping)]),
    );
  }
  return value;
}

async function buildSetup(
  steps: Array<Record<string, unknown>>,
  mapping: Record<string, string>,
): Promise<void> {
  for (const step of steps) {
    const type = step.type as string;
    if (type === "symlink-tamper") continue;
    const path = substitute(step.path, mapping) as string;
    if (type === "dir") {
      await mkdir(path, { recursive: true });
    } else if (type === "file") {
      await mkdir(dirname(path), { recursive: true });
      await writeFile(path, "data\n", "utf8");
    } else if (type === "symlink") {
      const target = substitute(step.target, mapping) as string;
      await mkdir(dirname(path), { recursive: true });
      await rm(path, { force: true });
      await symlink(target, path);
    }
  }
}

function shouldSkip(case_: Record<string, unknown>): boolean {
  const platform = case_.platform as string[] | undefined;
  if (!platform) return false;
  if (platform.includes("win32") && !IS_WIN32) return true;
  if (platform.includes("posix") && IS_WIN32) return true;
  return false;
}

for (const case_ of cases) {
  const id = case_.id as string;
  const contract = case_.contract as string;
  const skip = shouldSkip(case_) || contract !== "governor";

  const fn = async () => {
    const root = tmpDir();
    const repo = join(root, "repo");
    const outside = join(root, "outside");
    const scratch = join(root, "scratch");
    await mkdir(repo, { recursive: true });
    await mkdir(outside, { recursive: true });
    await mkdir(scratch, { recursive: true });

    const mapping: Record<string, string> = {
      "@REPO@": repo,
      "@OUTSIDE@": outside,
      "@SCRATCH@": scratch,
    };

    try {
      await buildSetup(case_.setup as Array<Record<string, unknown>>, mapping);
      const value = substitute(case_.value, mapping);
      const expectUnsafe = case_.expect === "unsafe";

      if (contract === "governor") {
        const key = case_.key as string;
        const repoRoot = realpathSync(repo);
        const found = unsafePaths({ [key]: value }, repoRoot);
        assert.equal(
          found.length > 0,
          expectUnsafe,
          `${id}: expected ${expectUnsafe ? "unsafe" : "allow"} but got ${found.length > 0 ? "unsafe" : "allow"}`,
        );
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  };

  if (skip) {
    test.skip(id, fn);
  } else {
    test(id, fn);
  }
}
