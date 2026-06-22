// src/index.ts
import { readFile as readFile2, realpath } from "node:fs/promises";
import { homedir as homedir2 } from "node:os";
import { isAbsolute as isAbsolute2, join as join2, relative as relative2 } from "node:path";
import { tool as tool2 } from "@opencode-ai/plugin";

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

// src/maintenance.ts
import { tool } from "@opencode-ai/plugin";
var MAINTENANCE_TOOL = "forge_memory_review";
var FORGE_FINISH_TOOL = "forge_finish_task";
var REVIEW_MEMORY_TEMPLATE = `Enter Forge memory review mode for this session.

Use the forge_memory_review tool to start, read context, apply a small validated batch, re-read context, and finish. Do not use edit, write, or bash. If a maintenance call fails, retry once; if it fails again, explain the failure and finish with status failed and a concrete reason.`;
function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function payloadRecord(value) {
  return isRecord(value) ? value : {};
}
function parseOperationsJSON(input) {
  const parsed = JSON.parse(input);
  if (!Array.isArray(parsed)) throw new Error("operations_json must decode to a JSON array");
  return parsed.filter(isRecord);
}
function installReviewMemoryCommand(config) {
  const commands = isRecord(config.command) ? config.command : {};
  config.command = {
    ...commands,
    "review-memory": {
      template: REVIEW_MEMORY_TEMPLATE,
      description: "Review Forge memory cards for the current session"
    }
  };
}
var MemoryMaintenanceAdapter = class {
  activeSessions = /* @__PURE__ */ new Set();
  shownRecommendations = /* @__PURE__ */ new Set();
  client;
  bridge;
  constructor(client, bridge) {
    this.client = client;
    this.bridge = bridge;
  }
  async request(operation, sessionID, payload = {}) {
    return await this.bridge.request(operation, { host_session_id: sessionID, ...payload });
  }
  async context(sessionID) {
    const response = await this.request("get_maintenance_context", sessionID);
    const payload = payloadRecord(response.payload);
    if (!response.ok || payload.mode !== "memory_review") {
      this.activeSessions.delete(sessionID);
      return null;
    }
    this.activeSessions.add(sessionID);
    return payload;
  }
  async before(sessionID, toolName) {
    if (toolName === MAINTENANCE_TOOL) return true;
    if (!this.activeSessions.has(sessionID)) return false;
    let context;
    try {
      context = await this.context(sessionID);
    } catch {
      throw new Error("Forge Alpha: maintenance bridge unavailable; exit /review-memory and retry");
    }
    const allowed = new Set(
      Array.isArray(context?.allowed_tools) ? context.allowed_tools.filter((value) => typeof value === "string") : []
    );
    if (!allowed.has(toolName)) {
      throw new Error("Forge Alpha: not allowed in maintenance mode; exit /review-memory first");
    }
    return true;
  }
  exemptFromCompaction(sessionID, toolName) {
    return toolName === MAINTENANCE_TOOL || this.activeSessions.has(sessionID);
  }
  async recommend(sessionID) {
    try {
      const response = await this.request("memory_maintenance_recommendation", sessionID);
      const payload = payloadRecord(response.payload);
      if (!response.ok || payload.recommend !== true || typeof payload.reason !== "string") return;
      const key = `${sessionID}:${payload.reason}`;
      if (this.shownRecommendations.has(key)) return;
      this.shownRecommendations.add(key);
      await this.client.tui.showToast({
        body: { message: `Forge Alpha: ${payload.reason}. Run /review-memory.`, variant: "warning" }
      });
    } catch {
    }
  }
  clear(sessionID) {
    this.activeSessions.delete(sessionID);
    for (const key of [...this.shownRecommendations]) {
      if (key.startsWith(`${sessionID}:`)) this.shownRecommendations.delete(key);
    }
  }
  tool() {
    return tool({
      description: "Proxy Forge memory review operations through the hidden maintenance backend.",
      args: {
        action: tool.schema.string().describe("One of: start, context, apply_batch, finish, recommendation"),
        operations_json: tool.schema.string().optional().describe("For apply_batch: a JSON array of operation objects"),
        status: tool.schema.string().optional().describe("For finish: completed or failed"),
        reason: tool.schema.string().optional().describe("Optional finish failure/success reason")
      },
      execute: async (args, context) => {
        const operations = { action: args.action };
        if (args.operations_json !== void 0) {
          operations.operations = parseOperationsJSON(args.operations_json);
        }
        if (args.status !== void 0) operations.status = args.status;
        if (args.reason !== void 0) operations.reason = args.reason;
        const response = await this.dispatch(context.sessionID, operations);
        if (!response.ok) {
          throw new Error(response.user_message || `Forge Alpha: ${response.reason || "maintenance request failed"}`);
        }
        return JSON.stringify(response.payload ?? {}, null, 2);
      }
    });
  }
  async dispatch(sessionID, args) {
    const action = args.action;
    if (action === "start") {
      const response = await this.request("start_memory_maintenance", sessionID);
      if (response.ok) this.activeSessions.add(sessionID);
      return response;
    }
    if (action === "context") return await this.request("get_maintenance_context", sessionID);
    if (action === "apply_batch") {
      return await this.request("apply_memory_review_batch", sessionID, {
        operations: args.operations ?? []
      });
    }
    if (action === "finish") {
      const response = await this.request("finish_memory_maintenance", sessionID, {
        status: args.status ?? "completed",
        reason: args.reason ?? ""
      });
      this.activeSessions.delete(sessionID);
      return response;
    }
    if (action === "recommendation") {
      return await this.request("memory_maintenance_recommendation", sessionID);
    }
    throw new Error("Forge Alpha: unsupported memory review action");
  }
};

// src/transport.ts
import { spawn } from "node:child_process";
import { delimiter, dirname as dirname2, resolve as resolve2 } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
var PROJECT_ROOT = resolve2(dirname2(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
function pythonCommand() {
  return process.env.FORGE_ALPHA_PYTHON?.trim() || process.env.PYTHON?.trim() || "python3";
}
function pythonEnv() {
  const pythonpath = [PROJECT_ROOT, process.env.PYTHONPATH].filter(Boolean).join(delimiter);
  return { ...process.env, PYTHONPATH: pythonpath };
}
var BridgeClient = class {
  child;
  lines;
  pending = [];
  stderr = "";
  ensureStarted() {
    if (this.child && !this.child.killed) return;
    const child = spawn(pythonCommand(), ["-m", "forge.plugin.bridge"], {
      cwd: PROJECT_ROOT,
      env: pythonEnv(),
      stdio: ["pipe", "pipe", "pipe"]
    });
    const lines = createInterface({ input: child.stdout });
    lines.on("line", (line) => {
      const next = this.pending.shift();
      if (!next) return;
      try {
        next.resolve(JSON.parse(line));
      } catch (error) {
        next.reject(error);
      }
    });
    child.stderr.on("data", (chunk) => {
      this.stderr += String(chunk);
      if (this.stderr.length > 4e3) this.stderr = this.stderr.slice(-4e3);
    });
    child.on("exit", () => {
      const error = new Error(this.stderr.trim() || "Forge Alpha bridge exited before replying");
      while (this.pending.length > 0) this.pending.shift()?.reject(error);
      this.lines?.close();
      this.lines = void 0;
      this.child = void 0;
    });
    this.child = child;
    this.lines = lines;
  }
  async request(operation, payload) {
    this.ensureStarted();
    if (!this.child) throw new Error("Forge Alpha bridge is not running");
    return await new Promise((resolveRequest, rejectRequest) => {
      this.pending.push({ resolve: resolveRequest, reject: rejectRequest });
      this.child.stdin.write(`${JSON.stringify({ schema_version: 1, operation, payload })}
`);
    });
  }
  close() {
    this.lines?.close();
    this.lines = void 0;
    if (this.child && !this.child.killed) this.child.kill();
    this.child = void 0;
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
function extractSessionID(properties) {
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return null;
  const values = properties;
  if (typeof values.sessionID === "string" && values.sessionID) return values.sessionID;
  const info = values.info;
  if (info && typeof info === "object" && !Array.isArray(info)) {
    const id = info.id;
    if (typeof id === "string" && id) return id;
  }
  return null;
}
function applyForgePermissions(config) {
  const existing = config.permission && typeof config.permission === "object" ? config.permission : {};
  config.permission = {
    ...existing,
    bash: withDangerousAsks(existing.bash),
    external_directory: existing.external_directory === "deny" ? "deny" : "ask"
  };
  installReviewMemoryCommand(config);
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
  const bridge = new BridgeClient();
  const maintenance = new MemoryMaintenanceAdapter(client, bridge);
  return {
    config: async (config) => {
      applyForgePermissions(config);
    },
    event: async ({ event }) => {
      const sessionId = extractSessionID(event.properties);
      if (event.type === "session.deleted") {
        if (sessionId) {
          governor.clearSession(sessionId);
          maintenance.clear(sessionId);
        }
        bridge.close();
        return;
      }
      if ((event.type === "session.created" || event.type === "session.idle") && sessionId) {
        await maintenance.recommend(sessionId);
      }
    },
    "tool.execute.before": async (input, output) => {
      if (await maintenance.before(input.sessionID, input.tool)) return;
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
      if (input.tool === "forge_expand_output" || maintenance.exemptFromCompaction(input.sessionID, input.tool)) return;
      await compactTextResult(
        compactor,
        input.sessionID,
        input.tool,
        output
      );
      if (input.tool === FORGE_FINISH_TOOL) {
        await maintenance.recommend(input.sessionID);
      }
    },
    tool: {
      forge_expand_output: tool2({
        description: "Read exact line ranges or search a Forge-compacted tool output.",
        args: {
          handle: tool2.schema.string().describe("Handle shown in the compacted output"),
          start_line: tool2.schema.number().int().positive().optional(),
          end_line: tool2.schema.number().int().positive().optional(),
          query: tool2.schema.string().optional(),
          context_lines: tool2.schema.number().int().min(0).max(10).optional()
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
      }),
      [MAINTENANCE_TOOL]: maintenance.tool()
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
