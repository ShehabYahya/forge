import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface, type Interface as ReadLineInterface } from "node:readline";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type BridgePayload = Record<string, unknown>;
export type BridgeResponse = {
  schema_version: number;
  ok: boolean;
  decision: string;
  reason: string;
  replacement_output?: string | null;
  user_message?: string | null;
  capability_limited?: boolean;
  payload?: BridgePayload;
};

const FORGE_EXECUTABLE = process.env.FORGE_EXECUTABLE?.trim()
  || process.env.FORGE_ALPHA_EXECUTABLE?.trim();
const FORGE_PYTHON_BRIDGE = process.env.FORGE_PYTHON_BRIDGE === "1";

function programRoot(): string {
  const envProgram = process.env.FORGE_PROGRAM?.trim()
    || process.env.FORGE_ALPHA_PROGRAM?.trim();
  if (envProgram) return envProgram;
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

let _cachedExecutable: string | null = null;

async function resolveExecutable(): Promise<string> {
  if (FORGE_EXECUTABLE) return FORGE_EXECUTABLE;
  if (FORGE_PYTHON_BRIDGE) {
    return process.env.FORGE_PYTHON?.trim()
      || process.env.FORGE_ALPHA_PYTHON?.trim()
      || process.env.PYTHON?.trim()
      || "python3";
  }
  if (_cachedExecutable) return _cachedExecutable;

  const root = programRoot();
  const manifestPath = join(root, "active.json");
  try {
    const raw = await readFile(manifestPath, "utf8");
    const manifest = JSON.parse(raw);
    if (manifest && typeof manifest.executable === "string" && manifest.executable.trim()) {
      _cachedExecutable = resolve(root, manifest.executable.trim());
      return _cachedExecutable;
    }
  } catch {
    // manifest unreadable; fall through
  }

  _cachedExecutable = process.env.FORGE_PYTHON?.trim()
    || process.env.FORGE_ALPHA_PYTHON?.trim()
    || process.env.PYTHON?.trim()
    || "python3";
  return _cachedExecutable;
}

function bridgeArgs(executable: string): string[] {
  if (FORGE_EXECUTABLE) return ["bridge"];
  if (FORGE_PYTHON_BRIDGE) return ["-m", "forge.plugin.bridge"];
  if (executable.includes("python") || executable.includes("python3")) return ["-m", "forge.plugin.bridge"];
  return ["bridge"];
}

export class BridgeClient {
  private child?: ChildProcessWithoutNullStreams;
  private lines?: ReadLineInterface;
  private pending: Array<{
    resolve: (value: BridgeResponse) => void;
    reject: (reason?: unknown) => void;
  }> = [];
  private stderr = "";
  private started = false;

  private async ensureStarted(): Promise<void> {
    if (this.child && !this.child.killed) return;
    const executable = await resolveExecutable();
    const args = bridgeArgs(executable);
    const env: NodeJS.ProcessEnv = { ...process.env };
    if (executable.includes("python")) {
      const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
      env.PYTHONPATH = [projectRoot, process.env.PYTHONPATH].filter(Boolean).join(
        process.platform === "win32" ? ";" : ":",
      );
    }
    const child = spawn(executable, args, {
      stdio: ["pipe", "pipe", "pipe"],
      env,
    });
    const lines = createInterface({ input: child.stdout });
    lines.on("line", (line) => {
      const next = this.pending.shift();
      if (!next) return;
      try {
        next.resolve(JSON.parse(line) as BridgeResponse);
      } catch (error) {
        next.reject(error);
      }
    });
    child.stderr.on("data", (chunk) => {
      this.stderr += String(chunk);
      if (this.stderr.length > 4000) this.stderr = this.stderr.slice(-4000);
    });
    child.on("exit", () => {
      const error = new Error(this.stderr.trim() || "Forge bridge exited before replying");
      while (this.pending.length > 0) this.pending.shift()?.reject(error);
      this.lines?.close();
      this.lines = undefined;
      this.child = undefined;
    });
    this.child = child;
    this.lines = lines;
    this.started = true;
  }

  async request(operation: string, payload: Record<string, unknown>): Promise<BridgeResponse> {
    await this.ensureStarted();
    if (!this.child) throw new Error("Forge bridge is not running");
    return await new Promise<BridgeResponse>((resolveRequest, rejectRequest) => {
      this.pending.push({ resolve: resolveRequest, reject: rejectRequest });
      this.child!.stdin.write(`${JSON.stringify({ schema_version: 1, operation, payload })}\n`);
    });
  }

  close(): void {
    this.lines?.close();
    this.lines = undefined;
    if (this.child && !this.child.killed) this.child.kill();
    this.child = undefined;
    this.started = false;
  }
}
