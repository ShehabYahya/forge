import { createHash } from "node:crypto";
import { existsSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";

export const GovernorMode = {
  OFF: "off",
  REPORT: "report",
  ACTIVE: "active",
} as const;

export type GovernorMode = (typeof GovernorMode)[keyof typeof GovernorMode];

const VALID_MODES = new Set<string>(Object.values(GovernorMode));
const DUPLICATE_TOOLS = new Set(["read", "grep", "glob"]);
const PATH_KEYS = new Set([
  "path",
  "filepath",
  "file",
  "filename",
  "cwd",
  "directory",
  "destination",
  "target",
]);

export interface GovernorCapabilities {
  can_block_before: boolean;
  can_replace_output: boolean;
  can_request_confirmation: boolean;
}

export interface GovernorDecision {
  schema_version: number;
  ok: boolean;
  decision: "allow" | "warn" | "escalate" | "block";
  reason: string;
  capability_limited: boolean;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, canonicalize(child)]),
    );
  }
  return value;
}

export function fingerprint(toolName: string, args: Record<string, unknown>): string {
  const wire = JSON.stringify({
    arguments: canonicalize(args),
    tool: toolName.trim().toLowerCase(),
  });
  return createHash("sha256").update(wire).digest("hex");
}

function resolvedWithExistingAncestors(candidate: string): string {
  let probe = candidate;
  const suffix: string[] = [];
  while (!existsSync(probe)) {
    const parent = dirname(probe);
    if (parent === probe) return resolve(candidate);
    suffix.unshift(relative(parent, probe));
    probe = parent;
  }
  return resolve(realpathSync(probe), ...suffix);
}

function escapesRoot(candidate: string, repoRoot: string): boolean {
  const rel = relative(repoRoot, candidate);
  return rel === ".." || rel.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) || isAbsolute(rel);
}

export function unsafePaths(value: unknown, repoRoot: string): string[] {
  const found: string[] = [];

  function visit(item: unknown, key: string): void {
    if (item === null || item === undefined) return;
    if (Array.isArray(item)) {
      for (const child of item) visit(child, key);
      return;
    }
    if (typeof item === "object") {
      for (const [childKey, child] of Object.entries(item as Record<string, unknown>)) {
        visit(child, childKey.toLowerCase());
      }
      return;
    }
    if (typeof item !== "string" || !PATH_KEYS.has(key)) return;
    if (item.includes("\0")) { found.push(item); return; }
    try {
      const joined = isAbsolute(item) ? resolve(item) : resolve(repoRoot, item);
      if (escapesRoot(resolvedWithExistingAncestors(joined), repoRoot)) found.push(item);
    } catch {
      found.push(item);
    }
  }

  visit(value, "");
  return found;
}

export function dangerousCommandReason(command: string): string | null {
  const normalized = command.toLowerCase().replace(/\s+/g, " ").trim();
  if (!normalized) return null;

  if (/(^|[;&|]\s*|\s)(?:command\s+)?rm\s+(?:(?:-[^\s]*[rf][^\s]*|--recursive|--force)\s+){2,}/.test(normalized)) {
    return "recursive forced removal requires approval";
  }
  if (/(^|[;&|]\s*|\s)(?:command\s+)?rm\s+-[^\s]*r[^\s]*f[^\s]*(?:\s|$)/.test(normalized)
      || /(^|[;&|]\s*|\s)(?:command\s+)?rm\s+-[^\s]*f[^\s]*r[^\s]*(?:\s|$)/.test(normalized)) {
    return "recursive forced removal requires approval";
  }
  if (/\bgit(?:\s+-c\s+\S+|\s+-c\S+|\s+-C\s+\S+)*\s+(?:reset\s+--hard|clean\s+-[^\s]*f|push\b[^;&|]*--force(?:-with-lease)?)/i.test(command)) {
    return "destructive Git command requires approval";
  }
  if (/(^|[;&|]\s*|\s)(sudo|mkfs(?:\.\w+)?|shutdown|reboot|poweroff)(?:\s|$)/.test(normalized)) {
    return "privileged or system command requires approval";
  }
  if (/(^|[;&|]\s*|\s)(dd|chmod|chown)\s+/.test(normalized)) {
    return "high-impact filesystem command requires approval";
  }
  return null;
}

export class ContextGovernor {
  private readonly mode: GovernorMode;
  private readonly repoRoot: string;
  private readonly capabilities: GovernorCapabilities;
  private readonly recentBySession = new Map<string, Array<[number, string]>>();
  private readonly duplicateCount: number;
  private readonly duplicateSeconds: number;

  constructor(
    mode: GovernorMode | string,
    repoRoot: string,
    capabilities: Partial<GovernorCapabilities> = {},
    duplicateCount = 16,
    duplicateSeconds = 60,
  ) {
    if (!VALID_MODES.has(String(mode))) throw new Error(`invalid governor mode: ${mode}`);
    this.mode = String(mode) as GovernorMode;
    this.repoRoot = resolvedWithExistingAncestors(resolve(repoRoot));
    this.capabilities = {
      can_block_before: false,
      can_replace_output: false,
      can_request_confirmation: false,
      ...capabilities,
    };
    this.duplicateCount = duplicateCount;
    this.duplicateSeconds = duplicateSeconds;
  }

  before(sessionId: string, toolName: string, args: Record<string, unknown>): GovernorDecision {
    if (!sessionId || !toolName || typeof args !== "object" || args === null) {
      return this.decision("block", "invalid governor input", "can_block_before");
    }
    if (this.mode === GovernorMode.OFF) return this.decision("allow", "governor is off");

    const normalizedTool = toolName.trim().toLowerCase();
    if (DUPLICATE_TOOLS.has(normalizedTool)) {
      const duplicate = this.trackDuplicate(sessionId, fingerprint(normalizedTool, args));
      if (duplicate) {
        const action = this.mode === GovernorMode.ACTIVE ? "block" : "warn";
        return this.decision(
          action,
          "duplicate call blocked. Retrieve the previous result with forge_expand_output " +
            "using the handle from the earlier output, or vary your arguments.",
          "can_block_before",
        );
      }
    }

    const command = String(args.command ?? args.cmd ?? "");
    const dangerous = dangerousCommandReason(command);
    if (dangerous) {
      const action = this.mode === GovernorMode.ACTIVE ? "escalate" : "warn";
      return this.decision(action, dangerous, "can_request_confirmation");
    }

    const unsafe = unsafePaths(args, this.repoRoot);
    if (unsafe.length > 0) {
      const action = this.mode === GovernorMode.ACTIVE ? "escalate" : "warn";
      return this.decision(
        action,
        `path is outside the controlled repository: ${unsafe[0]}`,
        "can_request_confirmation",
      );
    }

    return this.decision("allow", "no policy concern detected");
  }

  clearSession(sessionId: string): void {
    this.recentBySession.delete(sessionId);
  }

  private trackDuplicate(sessionId: string, key: string): boolean {
    const now = Date.now() / 1000;
    const recent = this.recentBySession.get(sessionId) ?? [];
    while (
      recent.length > 0
      && (recent.length >= this.duplicateCount || now - recent[0][0] > this.duplicateSeconds)
    ) {
      recent.shift();
    }
    const duplicate = recent.some(([, existing]) => existing === key);
    recent.push([now, key]);
    this.recentBySession.set(sessionId, recent);
    return duplicate;
  }

  private decision(
    requested: GovernorDecision["decision"],
    reason: string,
    needs?: keyof GovernorCapabilities,
  ): GovernorDecision {
    let decision = requested;
    let capabilityLimited = false;
    if (this.mode === GovernorMode.REPORT && decision !== "allow" && decision !== "warn") {
      decision = "warn";
    }
    if (this.mode === GovernorMode.ACTIVE && needs && !this.capabilities[needs]) {
      capabilityLimited = true;
      decision = "warn";
      reason += `; adapter lacks ${needs}`;
    }
    return {
      schema_version: 1,
      ok: true,
      decision,
      reason,
      capability_limited: capabilityLimited,
    };
  }
}
