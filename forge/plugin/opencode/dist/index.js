// src/index.ts
import { tool } from "@opencode-ai/plugin";
import { readFile as readFile2, realpath } from "node:fs/promises";
import { homedir as homedir2 } from "node:os";
import { isAbsolute as isAbsolute2, join as join2, relative as relative2 } from "node:path";

// src/compaction.ts
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
var HANDLE = /^fo_[0-9a-f]{32}$/;
var ANSI = /\x1b\[[0-?]*[ -/]*[@-~]/g;
var SECRET_PATTERNS = [
  /(api[_-]?key|token|secret|password)(\s*[=:]\s*)[^\s,;]+/gi,
  /(https?:\/\/[^:/\s]+:)[^@/\s]+@/gi
];
function runtimeRoot() {
  return process.env.FORGE_ALPHA_HOME?.trim() || join(homedir(), ".forge-alpha");
}
function redact(value) {
  let output = value;
  for (const pattern of SECRET_PATTERNS) {
    output = output.replace(pattern, (_match, first, second) => {
      return first + (second ?? "") + "[REDACTED]";
    });
  }
  return output;
}
function cleanLine(value) {
  return value.replace(ANSI, "").replace(/\s+/g, " ").trim();
}
function splitLines(content) {
  const lines = content.split(/\r?\n/);
  if (lines.length > 1 && lines.at(-1) === "") lines.pop();
  return lines;
}
function clipped(value, limit = 180) {
  if (value.length <= limit) return value;
  return value.slice(0, limit - 3).trimEnd() + "...";
}
function summarizeRange(lines, start, end) {
  const range = lines.slice(start - 1, end);
  const meaningful = range.map(cleanLine).filter(Boolean);
  const errors = meaningful.filter((line) => /\b(error|failed|failure|exception|fatal)\b/i.test(line)).length;
  const warnings = meaningful.filter((line) => /\bwarn(?:ing)?\b/i.test(line)).length;
  const passed = meaningful.filter((line) => /\b(pass(?:ed)?|success|ok)\b/i.test(line)).length;
  const signals = [
    errors ? `${errors} error signal${errors === 1 ? "" : "s"}` : "",
    warnings ? `${warnings} warning${warnings === 1 ? "" : "s"}` : "",
    passed ? `${passed} pass signal${passed === 1 ? "" : "s"}` : ""
  ].filter(Boolean);
  const first = meaningful[0] ?? "blank lines";
  const last = meaningful.at(-1);
  const sample = last && last !== first ? `${clipped(first, 120)} ... ${clipped(last, 120)}` : clipped(first);
  return `${signals.length ? signals.join(", ") + "; " : ""}${sample}`;
}
function buildSummary(handle, toolName, content, maxRanges) {
  const lines = splitLines(content);
  const desiredRanges = Math.min(
    maxRanges,
    Math.max(1, Math.ceil(lines.length / 80), Math.ceil(content.length / 6e3))
  );
  const linesPerRange = Math.max(1, Math.ceil(lines.length / desiredRanges));
  const summaries = [];
  for (let start = 1; start <= lines.length; start += linesPerRange) {
    const end = Math.min(lines.length, start + linesPerRange - 1);
    summaries.push(`L${start}-L${end}: ${summarizeRange(lines, start, end)}`);
  }
  return [
    `[Forge compacted ${toolName} output: ${lines.length} lines, ${content.length} chars]`,
    `Handle: ${handle}`,
    "Each summary maps to exact original line numbers:",
    ...summaries,
    "",
    `Read exact lines with forge_expand_output(handle="${handle}", start_line=N, end_line=M).`,
    `Search without reading everything with forge_expand_output(handle="${handle}", query="text").`
  ].join("\n");
}
var ToolOutputCompactor = class {
  root;
  largeOutputChars;
  maxSummaryRanges;
  maxExpandLines;
  maxExpandChars;
  constructor(root = join(runtimeRoot(), "tool-results"), largeOutputChars = 8e3, maxSummaryRanges = 20, maxExpandLines = 240, maxExpandChars = 64e3) {
    this.root = root;
    this.largeOutputChars = largeOutputChars;
    this.maxSummaryRanges = maxSummaryRanges;
    this.maxExpandLines = maxExpandLines;
    this.maxExpandChars = maxExpandChars;
  }
  shouldCompact(content) {
    return content.length > this.largeOutputChars;
  }
  async compact(sessionId, toolName, content) {
    if (!this.shouldCompact(content)) return null;
    if (!sessionId) throw new Error("session_id is required for compacted output");
    await mkdir(this.root, { recursive: true, mode: 448 });
    const handle = `fo_${randomBytes(16).toString("hex")}`;
    const sanitized = redact(content);
    const metadata = {
      schema_version: 1,
      handle,
      session_id: sessionId,
      tool_name: toolName,
      chars: sanitized.length,
      line_count: splitLines(sanitized).length,
      sha256: createHash("sha256").update(sanitized).digest("hex")
    };
    await Promise.all([
      writeFile(this.rawPath(handle), sanitized, { encoding: "utf8", mode: 384, flag: "wx" }),
      writeFile(this.metadataPath(handle), JSON.stringify(metadata), { encoding: "utf8", mode: 384, flag: "wx" })
    ]);
    return {
      ...metadata,
      replacement_output: buildSummary(handle, toolName, sanitized, this.maxSummaryRanges)
    };
  }
  async expand(sessionId, handle, startLine = 1, endLine) {
    const { metadata, content, lines } = await this.loadOwned(sessionId, handle);
    if (!Number.isInteger(startLine) || startLine < 1 || startLine > lines.length) {
      throw new Error("start_line is outside the stored output");
    }
    const requestedEnd = endLine ?? Math.min(lines.length, startLine + this.maxExpandLines - 1);
    if (!Number.isInteger(requestedEnd) || requestedEnd < startLine) {
      throw new Error("end_line must be an integer greater than or equal to start_line");
    }
    if (requestedEnd - startLine + 1 > this.maxExpandLines) {
      throw new Error(`one expansion may read at most ${this.maxExpandLines} lines`);
    }
    const boundedEnd = Math.min(lines.length, requestedEnd);
    const selected = lines.slice(startLine - 1, boundedEnd).join("\n");
    const truncated = selected.length > this.maxExpandChars;
    const returned = truncated ? selected.slice(0, this.maxExpandChars) : selected;
    return {
      handle,
      start_line: startLine,
      end_line: boundedEnd,
      total_lines: metadata.line_count,
      content: returned,
      complete: boundedEnd >= lines.length && !truncated,
      truncated
    };
  }
  async search(sessionId, handle, query, contextLines = 2) {
    if (!query.trim()) throw new Error("query must be non-empty");
    if (!Number.isInteger(contextLines) || contextLines < 0 || contextLines > 10) {
      throw new Error("context_lines must be between 0 and 10");
    }
    const { lines } = await this.loadOwned(sessionId, handle);
    const needle = query.toLowerCase();
    const indexes = lines.map((line, index) => line.toLowerCase().includes(needle) ? index : -1).filter((index) => index >= 0);
    const matches = [];
    let returnedChars = 0;
    let characterLimited = false;
    for (const index of indexes.slice(0, 20)) {
      const start = Math.max(0, index - contextLines);
      const end = Math.min(lines.length - 1, index + contextLines);
      const fullContent = lines.slice(start, end + 1).join("\n");
      const remaining = this.maxExpandChars - returnedChars;
      if (remaining <= 0) {
        characterLimited = true;
        break;
      }
      const content = fullContent.slice(0, remaining);
      matches.push({
        start_line: start + 1,
        end_line: end + 1,
        content
      });
      returnedChars += content.length;
      if (content.length < fullContent.length) {
        characterLimited = true;
        break;
      }
    }
    return {
      handle,
      query,
      matches,
      total_matches: indexes.length,
      truncated: characterLimited || indexes.length > matches.length
    };
  }
  async loadOwned(sessionId, handle) {
    if (!HANDLE.test(handle)) throw new Error("malformed compacted-output handle");
    const metadata = JSON.parse(await readFile(this.metadataPath(handle), "utf8"));
    if (metadata.handle !== handle || metadata.schema_version !== 1) {
      throw new Error("compacted-output metadata mismatch");
    }
    if (metadata.session_id !== sessionId) {
      throw new Error("compacted output belongs to another session");
    }
    const content = await readFile(this.rawPath(handle), "utf8");
    if (createHash("sha256").update(content).digest("hex") !== metadata.sha256) {
      throw new Error("compacted output failed integrity verification");
    }
    return { metadata, content, lines: splitLines(content) };
  }
  rawPath(handle) {
    return join(this.root, `${handle}.raw`);
  }
  metadataPath(handle) {
    return join(this.root, `${handle}.json`);
  }
};

// src/governor.ts
import { createHash as createHash2 } from "node:crypto";
import { existsSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";
var GovernorMode = {
  OFF: "off",
  REPORT: "report",
  ACTIVE: "active"
};
var VALID_MODES = new Set(Object.values(GovernorMode));
var DUPLICATE_TOOLS = /* @__PURE__ */ new Set(["read", "grep", "glob"]);
var PATH_KEYS = /* @__PURE__ */ new Set([
  "path",
  "filepath",
  "file",
  "filename",
  "cwd",
  "directory",
  "destination",
  "target"
]);
function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, child]) => [key, canonicalize(child)])
    );
  }
  return value;
}
function fingerprint(toolName, args) {
  const wire = JSON.stringify({
    arguments: canonicalize(args),
    tool: toolName.trim().toLowerCase()
  });
  return createHash2("sha256").update(wire).digest("hex");
}
function resolvedWithExistingAncestors(candidate) {
  let probe = candidate;
  const suffix = [];
  while (!existsSync(probe)) {
    const parent = dirname(probe);
    if (parent === probe) return resolve(candidate);
    suffix.unshift(relative(parent, probe));
    probe = parent;
  }
  return resolve(realpathSync(probe), ...suffix);
}
function escapesRoot(candidate, repoRoot) {
  const rel = relative(repoRoot, candidate);
  return rel === ".." || rel.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) || isAbsolute(rel);
}
function unsafePaths(value, repoRoot) {
  const found = [];
  function visit(item, key) {
    if (item === null || item === void 0) return;
    if (Array.isArray(item)) {
      for (const child of item) visit(child, key);
      return;
    }
    if (typeof item === "object") {
      for (const [childKey, child] of Object.entries(item)) {
        visit(child, childKey.toLowerCase());
      }
      return;
    }
    if (typeof item !== "string" || !PATH_KEYS.has(key)) return;
    const joined = isAbsolute(item) ? resolve(item) : resolve(repoRoot, item);
    if (escapesRoot(resolvedWithExistingAncestors(joined), repoRoot)) found.push(item);
  }
  visit(value, "");
  return found;
}
function dangerousCommandReason(command) {
  const normalized = command.toLowerCase().replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  if (/(^|[;&|]\s*|\s)(?:command\s+)?rm\s+(?:(?:-[^\s]*[rf][^\s]*|--recursive|--force)\s+){2,}/.test(normalized)) {
    return "recursive forced removal requires approval";
  }
  if (/(^|[;&|]\s*|\s)(?:command\s+)?rm\s+-[^\s]*r[^\s]*f[^\s]*(?:\s|$)/.test(normalized) || /(^|[;&|]\s*|\s)(?:command\s+)?rm\s+-[^\s]*f[^\s]*r[^\s]*(?:\s|$)/.test(normalized)) {
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
var ContextGovernor = class {
  mode;
  repoRoot;
  capabilities;
  recentBySession = /* @__PURE__ */ new Map();
  duplicateCount;
  duplicateSeconds;
  constructor(mode, repoRoot, capabilities = {}, duplicateCount = 16, duplicateSeconds = 60) {
    if (!VALID_MODES.has(String(mode))) throw new Error(`invalid governor mode: ${mode}`);
    this.mode = String(mode);
    this.repoRoot = resolvedWithExistingAncestors(resolve(repoRoot));
    this.capabilities = {
      can_block_before: false,
      can_replace_output: false,
      can_request_confirmation: false,
      ...capabilities
    };
    this.duplicateCount = duplicateCount;
    this.duplicateSeconds = duplicateSeconds;
  }
  before(sessionId, toolName, args) {
    if (!sessionId || !toolName || typeof args !== "object" || args === null) {
      return this.decision("block", "invalid governor input", "can_block_before");
    }
    if (this.mode === GovernorMode.OFF) return this.decision("allow", "governor is off");
    const normalizedTool = toolName.trim().toLowerCase();
    if (DUPLICATE_TOOLS.has(normalizedTool)) {
      const duplicate = this.trackDuplicate(sessionId, fingerprint(normalizedTool, args));
      if (duplicate) {
        const action = this.mode === GovernorMode.ACTIVE ? "block" : "warn";
        return this.decision(action, "exact duplicate read in this session", "can_block_before");
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
        "can_request_confirmation"
      );
    }
    return this.decision("allow", "no policy concern detected");
  }
  clearSession(sessionId) {
    this.recentBySession.delete(sessionId);
  }
  trackDuplicate(sessionId, key) {
    const now = Date.now() / 1e3;
    const recent = this.recentBySession.get(sessionId) ?? [];
    while (recent.length > 0 && (recent.length >= this.duplicateCount || now - recent[0][0] > this.duplicateSeconds)) {
      recent.shift();
    }
    const duplicate = recent.some(([, existing]) => existing === key);
    recent.push([now, key]);
    this.recentBySession.set(sessionId, recent);
    return duplicate;
  }
  decision(requested, reason, needs) {
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
      capability_limited: capabilityLimited
    };
  }
};

// src/index.ts
var DANGEROUS_BASH_PERMISSION_PATTERNS = [
  "rm *",
  "sudo *",
  "mkfs *",
  "mkfs.* *",
  "shutdown *",
  "reboot *",
  "poweroff *",
  "dd *",
  "chmod *",
  "chown *",
  "git reset *",
  "git * reset *",
  "git clean *",
  "git * clean *",
  "git push *--force*",
  "git * push *--force*"
];
function withDangerousAsks(existing) {
  if (existing === "deny") return "deny";
  const configured = existing && typeof existing === "object" ? existing : {};
  const fallback = typeof existing === "string" ? existing : configured["*"] ?? "allow";
  const rules = { "*": fallback, ...configured };
  for (const pattern of DANGEROUS_BASH_PERMISSION_PATTERNS) {
    if (configured[pattern] !== "deny") rules[pattern] = "ask";
  }
  return rules;
}
function applyForgePermissions(config) {
  const existing = config.permission && typeof config.permission === "object" ? config.permission : {};
  config.permission = {
    ...existing,
    bash: withDangerousAsks(existing.bash),
    external_directory: existing.external_directory === "deny" ? "deny" : "ask"
  };
}
async function compactTextResult(compactor, sessionId, toolName, output) {
  if (typeof output.output === "string") {
    const source = await recoverFullOutput(output) ?? output.output;
    const compacted = await compactor.compact(sessionId, toolName, source);
    if (compacted) output.output = compacted.replacement_output;
    return;
  }
  if (!Array.isArray(output.content)) return;
  for (const item of output.content) {
    if (!item || typeof item !== "object") continue;
    const content = item;
    if (content.type !== "text" || typeof content.text !== "string") continue;
    const compacted = await compactor.compact(sessionId, toolName, content.text);
    if (compacted) content.text = compacted.replacement_output;
  }
}
async function recoverFullOutput(output) {
  const metadata = output.metadata;
  if (!metadata || typeof metadata !== "object") return null;
  const values = metadata;
  if (values.truncated !== true || typeof values.outputPath !== "string") return null;
  try {
    const dataRoot = process.env.XDG_DATA_HOME?.trim() || join2(homedir2(), ".local", "share");
    const allowedRoot = await realpath(join2(dataRoot, "opencode", "tool-output"));
    const candidate = await realpath(values.outputPath);
    const rel = relative2(allowedRoot, candidate);
    if (rel === ".." || rel.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) || isAbsolute2(rel)) {
      return null;
    }
    return await readFile2(candidate, "utf8");
  } catch {
    return null;
  }
}
var ForgeAlphaPlugin = async ({ client, worktree }) => {
  if (!worktree) return {};
  const governor = new ContextGovernor("active", worktree, {
    can_block_before: true,
    can_replace_output: true,
    can_request_confirmation: true
  });
  const compactor = new ToolOutputCompactor();
  return {
    config: async (config) => {
      applyForgePermissions(config);
    },
    event: async ({ event }) => {
      if (event.type !== "session.deleted") return;
      const properties = event.properties;
      const sessionId = properties.sessionID ?? properties.info?.id;
      if (sessionId) governor.clearSession(sessionId);
    },
    "tool.execute.before": async (input, output) => {
      const result = governor.before(input.sessionID, input.tool, output.args ?? {});
      if (result.decision === "block") throw new Error(`Forge Alpha: ${result.reason}`);
      if (result.decision !== "warn" && result.decision !== "escalate") return;
      try {
        await client.tui.showToast({
          body: {
            message: result.decision === "escalate" ? `Forge Alpha: approval required - ${result.reason}` : `Forge Alpha: ${result.reason}`,
            variant: "warning"
          }
        });
      } catch {
      }
    },
    "tool.execute.after": async (input, output) => {
      if (input.tool === "forge_expand_output") return;
      await compactTextResult(
        compactor,
        input.sessionID,
        input.tool,
        output
      );
    },
    tool: {
      forge_expand_output: tool({
        description: "Read exact line ranges or search a Forge-compacted tool output.",
        args: {
          handle: tool.schema.string().describe("Handle shown in the compacted output"),
          start_line: tool.schema.number().int().positive().optional(),
          end_line: tool.schema.number().int().positive().optional(),
          query: tool.schema.string().optional(),
          context_lines: tool.schema.number().int().min(0).max(10).optional()
        },
        async execute(args, context) {
          if (args.query) {
            const result2 = await compactor.search(
              context.sessionID,
              args.handle,
              args.query,
              args.context_lines ?? 2
            );
            return JSON.stringify(result2, null, 2);
          }
          const result = await compactor.expand(
            context.sessionID,
            args.handle,
            args.start_line ?? 1,
            args.end_line
          );
          return [
            `[${result.handle} L${result.start_line}-L${result.end_line} of ${result.total_lines}]`,
            result.content,
            result.truncated ? "[Character limit reached; request a smaller line range.]" : ""
          ].filter(Boolean).join("\n");
        }
      })
    }
  };
};

// src/plugin.ts
var plugin_default = {
  id: "forge-alpha",
  server: ForgeAlphaPlugin
};
export {
  plugin_default as default
};
//# sourceMappingURL=index.js.map
