import { createHash, randomBytes } from "node:crypto";
import { writeFileSync, mkdirSync, appendFileSync, realpathSync, openSync, closeSync, unlinkSync } from "node:fs";
import { resolve, isAbsolute, relative } from "node:path";
import { env } from "node:process";

export const GovernorMode = {
  OFF: "off",
  REPORT: "report",
  ACTIVE: "active",
} as const;

export type GovernorMode = (typeof GovernorMode)[keyof typeof GovernorMode];

const VALID_MODES = new Set<string>(["off", "report", "active"]);

export interface GovernorCapabilities {
  can_block_before: boolean;
  can_replace_output: boolean;
  can_request_confirmation: boolean;
}

const DANGEROUS: RegExp[] = [
  /(^|\s)rm\s+(-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\b/,
  /\bgit\s+(reset\s+--hard|clean\s+-[^\s]*f|push\s+.*--force)\b/,
  /\b(?:sudo|mkfs|shutdown|reboot)\b/,
];

const SECRET_PATTERNS: RegExp[] = [
  /(api[_-]?key|token|secret|password)(\s*[=:]\s*)[^\s,;]+/gi,
  /(https?:\/\/[^:/\s]+:)[^@/\s]+@/gi,
];

const PATH_KEYS = new Set([
  "path", "file", "filename", "cwd", "directory", "destination", "target",
]);

function defaultRuntimeRoot(): string {
  const home = env.HOME ?? env.USERPROFILE ?? "/tmp";
  return `${home}/.forge-alpha`;
}

function redact(value: string): string {
  let out = value;
  for (const pattern of SECRET_PATTERNS) {
    out = out.replace(pattern, (_match, g1: string, g2?: string) => {
      return g1 + (g2 ?? "") + "[REDACTED]";
    });
  }
  return out;
}

export function estimateTokens(value: string): number {
  return Math.ceil(value.length / 4);
}

export function fingerprint(toolName: string, args: Record<string, unknown>): string {
  const ordered: Record<string, unknown> = {};
  for (const key of Object.keys(args).sort()) {
    ordered[key] = args[key];
  }
  const wire = JSON.stringify({ arguments: ordered, tool: toolName.trim().toLowerCase() });
  return createHash("sha256").update(wire).digest("hex");
}

function lockedAppend(filePath: string, data: string): void {
  const lockPath = filePath + ".lock";
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      const fd = openSync(lockPath, "wx");
      try {
        appendFileSync(filePath, data, "utf-8");
      } finally {
        try { closeSync(fd); } catch { /* ignore */ }
        unlinkSync(lockPath);
      }
      return;
    } catch {
      if (attempt < 19) {
        const waitUntil = Date.now() + Math.min(5 * Math.pow(2, attempt), 200);
        while (Date.now() < waitUntil) { /* spin */ }
      }
    }
  }
  console.warn("Forge Alpha: failed to acquire lock for result store after 20 attempts, writing without lock");
  appendFileSync(filePath, data, "utf-8");
}

function storeResult(runtimeRoot: string, sessionId: string, content: string): string {
  const root = `${runtimeRoot}/tool-results`;
  mkdirSync(root, { recursive: true });
  const handle = "fr_" + randomBytes(16).toString("hex");
  const sanitized = redact(content);
  writeFileSync(`${root}/${handle}.raw`, sanitized, "utf-8");
  const metadata = JSON.stringify({
    schema_version: 1,
    handle,
    task_id: sessionId,
    path: `${handle}.raw`,
    chars: sanitized.length,
    sha256: createHash("sha256").update(sanitized).digest("hex"),
  }) + "\n";
  lockedAppend(`${root}/index.jsonl`, metadata);
  return handle;
}

function unsafePaths(value: unknown, repoRoot: string): string[] {
  const found: string[] = [];

  function visit(item: unknown, key: string): void {
    if (item === null || item === undefined) return;
    if (Array.isArray(item)) {
      for (const child of item) visit(child, key);
    } else if (typeof item === "object") {
      for (const [childKey, child] of Object.entries(item as Record<string, unknown>)) {
        visit(child, childKey.toLowerCase());
      }
    } else if (typeof item === "string" && PATH_KEYS.has(key)) {
      const candidate = item;
      const joined = isAbsolute(candidate) ? candidate : resolve(repoRoot, candidate);
      try {
        const resolved = realpathSync(joined);
        const rel = relative(repoRoot, resolved);
        if (rel.startsWith("..")) {
          found.push(candidate);
        }
      } catch {
        const rel = relative(repoRoot, joined);
        if (rel.startsWith("..")) {
          found.push(candidate);
        }
      }
    }
  }

  visit(value, "");
  return found;
}

export class ContextGovernor {
  private mode: GovernorMode;
  private repoRoot: string;
  private runtimeRoot: string;
  private capabilities: GovernorCapabilities;
  private recent: Array<[number, string]> = [];
  private duplicateCount: number;
  private duplicateSeconds: number;
  private largeOutputTokens: number;

  constructor(
    mode: GovernorMode | string,
    repoRoot: string,
    capabilities: Partial<GovernorCapabilities> = {},
    runtimeRoot?: string,
    duplicateCount = 16,
    duplicateSeconds = 60,
    largeOutputTokens = 2000,
  ) {
    const m = String(mode);
    if (!VALID_MODES.has(m)) {
      throw new Error(`invalid governor mode: ${m}`);
    }
    this.mode = m as GovernorMode;
    try {
      this.repoRoot = realpathSync(repoRoot);
    } catch {
      this.repoRoot = resolve(repoRoot);
    }
    this.runtimeRoot = runtimeRoot ?? defaultRuntimeRoot();
    this.capabilities = {
      can_block_before: false,
      can_replace_output: false,
      can_request_confirmation: false,
      ...capabilities,
    };
    this.duplicateCount = duplicateCount;
    this.duplicateSeconds = duplicateSeconds;
    this.largeOutputTokens = largeOutputTokens;
  }

  before(sessionId: string, toolName: string, args: Record<string, unknown>): GovernorDecision {
    if (!sessionId || !toolName || typeof args !== "object" || args === null) {
      return this.decision("block", "invalid governor input", "can_block_before");
    }
    if (this.mode === GovernorMode.OFF) {
      return this.decision("allow", "governor is off");
    }

    const now = Date.now() / 1000;
    const key = fingerprint(toolName, args);

    while (
      this.recent.length > 0 &&
      (this.recent.length >= this.duplicateCount ||
        now - this.recent[0][0] > this.duplicateSeconds)
    ) {
      this.recent.shift();
    }

    const duplicate = this.recent.some(([, existing]) => existing === key);
    this.recent.push([now, key]);

    if (duplicate) {
      const action = this.mode === GovernorMode.ACTIVE ? "block" : "warn";
      return this.decision(action, "exact duplicate tool call", "can_block_before");
    }

    const command = String(args.command ?? args.cmd ?? "");
    if (DANGEROUS.some((p) => p.test(command))) {
      return this.decision(
        this.mode === GovernorMode.ACTIVE ? "escalate" : "warn",
        "dangerous command requires user confirmation",
        "can_request_confirmation",
      );
    }

    const unsafe = unsafePaths(args, this.repoRoot);
    if (unsafe.length > 0) {
      return this.decision(
        this.mode === GovernorMode.ACTIVE ? "escalate" : "warn",
        "path is outside the controlled repository: " + unsafe[0],
        "can_request_confirmation",
      );
    }

    return this.decision("allow", "no policy concern detected");
  }

  after(sessionId: string, _toolName: string, output: string): GovernorDecision {
    if (typeof output !== "string") {
      return this.decision("warn", "tool output was not text");
    }
    if (this.mode === GovernorMode.OFF || estimateTokens(output) <= this.largeOutputTokens) {
      return this.decision("allow", "output is within limit");
    }
    if (this.mode === GovernorMode.REPORT) {
      return this.decision("warn", "large tool output detected");
    }
    if (!this.capabilities.can_replace_output) {
      return this.decision("warn", "large output cannot be replaced by this adapter", undefined, true);
    }
    const handle = storeResult(this.runtimeRoot, sessionId, output);
    const replacement = `Large output stored as ${handle}. Use forge_expand_tool_result with this task id.`;
    return this.decision("replace", "large output stored for bounded expansion", undefined, false, {
      replacement_output: replacement,
      handle,
    });
  }

  private decision(
    decision: string,
    reason: string,
    needs?: string,
    capabilityLimited = false,
    extra: Record<string, unknown> = {},
  ): GovernorDecision {
    let d = decision;
    let limited = capabilityLimited;
    if (this.mode === GovernorMode.REPORT && d !== "allow" && d !== "warn") {
      d = "warn";
    }
    if (this.mode === GovernorMode.ACTIVE && needs && !(this.capabilities as Record<string, boolean>)[needs]) {
      limited = true;
      d = "warn";
      reason += `; adapter lacks ${needs}`;
    }
    return {
      schema_version: 1,
      ok: true,
      decision: d,
      reason,
      replacement_output: (extra.replacement_output as string) ?? null,
      capability_limited: limited,
      handle: (extra.handle as string) ?? null,
    };
  }
}

export interface GovernorDecision {
  schema_version: number;
  ok: boolean;
  decision: string;
  reason: string;
  replacement_output: string | null;
  capability_limited: boolean;
  handle?: string | null;
}
