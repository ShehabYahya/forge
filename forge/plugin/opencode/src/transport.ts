import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { delimiter, dirname, resolve } from "node:path";
import { createInterface, type Interface as ReadLineInterface } from "node:readline";
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

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");

function pythonCommand(): string {
  return process.env.FORGE_ALPHA_PYTHON?.trim()
    || process.env.PYTHON?.trim()
    || "python3";
}

function pythonEnv(): NodeJS.ProcessEnv {
  const pythonpath = [PROJECT_ROOT, process.env.PYTHONPATH].filter(Boolean).join(delimiter);
  return { ...process.env, PYTHONPATH: pythonpath };
}

export class BridgeClient {
  private child?: ChildProcessWithoutNullStreams;
  private lines?: ReadLineInterface;
  private pending: Array<{
    resolve: (value: BridgeResponse) => void;
    reject: (reason?: unknown) => void;
  }> = [];
  private stderr = "";

  private ensureStarted(): void {
    if (this.child && !this.child.killed) return;
    const child = spawn(pythonCommand(), ["-m", "forge.plugin.bridge"], {
      cwd: PROJECT_ROOT,
      env: pythonEnv(),
      stdio: ["pipe", "pipe", "pipe"],
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
      const error = new Error(this.stderr.trim() || "Forge Alpha bridge exited before replying");
      while (this.pending.length > 0) this.pending.shift()?.reject(error);
      this.lines?.close();
      this.lines = undefined;
      this.child = undefined;
    });
    this.child = child;
    this.lines = lines;
  }

  async request(operation: string, payload: Record<string, unknown>): Promise<BridgeResponse> {
    this.ensureStarted();
    if (!this.child) throw new Error("Forge Alpha bridge is not running");
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
  }
}
