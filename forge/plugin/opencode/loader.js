/**
 * Stable Forge global plugin loader.
 *
 * Installed once in OpenCode's global plugin discovery directory.
 * Resolves the active version manifest, then dynamically imports
 * the versioned plugin bundle. Never embeds a version-specific path.
 */

import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { type Plugin } from "@opencode-ai/plugin";

const ENV_PROGRAM = process.env.FORGE_PROGRAM?.trim() || process.env.FORGE_ALPHA_PROGRAM?.trim();

interface ActiveManifest {
  version: string;
  plugin: string;
  executable: string;
}

function programRoot(): string {
  if (ENV_PROGRAM) return ENV_PROGRAM;
  const platform = process.platform;
  if (platform === "win32") {
    return process.env.APPDATA
      ? join(process.env.APPDATA, "forge", "program")
      : join(homedir(), "AppData", "Roaming", "forge", "program");
  }
  if (platform === "darwin") {
    return join(homedir(), "Library", "Application Support", "forge", "program");
  }
  const xdg = process.env.XDG_DATA_HOME?.trim() || join(homedir(), ".local", "share");
  return join(xdg, "forge", "program");
}

async function readActiveManifest(): Promise<ActiveManifest> {
  const root = programRoot();
  const manifestPath = join(root, "active.json");
  let raw: string;
  try {
    raw = await readFile(manifestPath, "utf8");
  } catch {
    throw new Error(
      `Forge: no active manifest at ${manifestPath}. Run: forge install`,
    );
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`Forge: active manifest is not valid JSON at ${manifestPath}`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Forge: active manifest is not a JSON object");
  }
  const m = parsed as Record<string, unknown>;
  for (const key of ["version", "plugin", "executable"]) {
    if (typeof m[key] !== "string" || !(m[key] as string).trim()) {
      throw new Error(`Forge: active manifest missing required key: ${key}`);
    }
  }
  return {
    version: m.version as string,
    plugin: resolve(root, m.plugin as string),
    executable: resolve(root, m.executable as string),
  };
}

let _manifest: ActiveManifest | null = null;

export async function getActiveManifest(): Promise<ActiveManifest> {
  if (!_manifest) {
    _manifest = await readActiveManifest();
  }
  return _manifest;
}

let _executable: string | null = null;

export function getExecutable(): string {
  if (_executable) return _executable;
  if (ENV_PROGRAM) {
    _executable = join(ENV_PROGRAM, "forge");
    return _executable;
  }
  const platform = process.platform;
  const ext = platform === "win32" ? ".exe" : "";
  _executable = join(programRoot(), "active", "bin", `forge${ext}`);
  return _executable;
}

export function setExecutable(path: string): void {
  _executable = path;
}

const loader: Plugin = async ({ client, worktree }, options) => {
  const manifest = await getActiveManifest();

  try {
    const versionedModule = await import(manifest.plugin);
    const versionedPlugin: Plugin =
      versionedModule.default || versionedModule.ForgeAlphaPlugin;

    if (typeof versionedPlugin !== "function") {
      throw new Error("versioned plugin does not export a Plugin factory");
    }

    setExecutable(manifest.executable);
    return await versionedPlugin({ client, worktree }, options);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`Forge loader failed: ${message}`);
  }
};

export { loader as server };

export default loader;
