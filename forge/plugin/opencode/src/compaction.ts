import { createHash, randomBytes } from "node:crypto";
import { lstatSync, realpathSync } from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

const HANDLE = /^fo_[0-9a-f]{32}$/;
const ANSI = /\x1b\[[0-?]*[ -/]*[@-~]/g;
const SECRET_PATTERNS: RegExp[] = [
  /(api[_-]?key|token|secret|password)(\s*[=:]\s*)[^\s,;]+/gi,
  /(https?:\/\/[^:/\s]+:)[^@/\s]+@/gi,
];

type StoredMetadata = {
  schema_version: 1;
  handle: string;
  session_id: string;
  tool_name: string;
  chars: number;
  line_count: number;
  sha256: string;
};

export type CompactResult = StoredMetadata & {
  replacement_output: string;
};

export type Expansion = {
  handle: string;
  start_line: number;
  end_line: number;
  total_lines: number;
  content: string;
  complete: boolean;
  truncated: boolean;
};

export type SearchResult = {
  handle: string;
  query: string;
  matches: Array<{ start_line: number; end_line: number; content: string }>;
  total_matches: number;
  truncated: boolean;
};

function runtimeRoot(): string {
  return process.env.FORGE_HOME?.trim()
    || process.env.FORGE_ALPHA_HOME?.trim()
    || join(homedir(), ".forge");
}

function redact(value: string): string {
  let output = value;
  for (const pattern of SECRET_PATTERNS) {
    output = output.replace(pattern, (_match, first: string, second?: string) => {
      return first + (second ?? "") + "[REDACTED]";
    });
  }
  return output;
}

function cleanLine(value: string): string {
  return value.replace(ANSI, "").replace(/\s+/g, " ").trim();
}

function splitLines(content: string): string[] {
  const lines = content.split(/\r?\n/);
  if (lines.length > 1 && lines.at(-1) === "") lines.pop();
  return lines;
}

function clipped(value: string, limit = 180): string {
  if (value.length <= limit) return value;
  return value.slice(0, limit - 3).trimEnd() + "...";
}

function summarizeRange(lines: string[], start: number, end: number): string {
  const range = lines.slice(start - 1, end);
  const meaningful = range.map(cleanLine).filter(Boolean);
  const errors = meaningful.filter((line) => /\b(error|failed|failure|exception|fatal)\b/i.test(line)).length;
  const warnings = meaningful.filter((line) => /\bwarn(?:ing)?\b/i.test(line)).length;
  const passed = meaningful.filter((line) => /\b(pass(?:ed)?|success|ok)\b/i.test(line)).length;
  const signals = [
    errors ? `${errors} error signal${errors === 1 ? "" : "s"}` : "",
    warnings ? `${warnings} warning${warnings === 1 ? "" : "s"}` : "",
    passed ? `${passed} pass signal${passed === 1 ? "" : "s"}` : "",
  ].filter(Boolean);
  const first = meaningful[0] ?? "blank lines";
  const last = meaningful.at(-1);
  const sample = last && last !== first ? `${clipped(first, 120)} ... ${clipped(last, 120)}` : clipped(first);
  return `${signals.length ? signals.join(", ") + "; " : ""}${sample}`;
}

function buildSummary(handle: string, toolName: string, content: string, maxRanges: number): string {
  const lines = splitLines(content);
  const desiredRanges = Math.min(
    maxRanges,
    Math.max(1, Math.ceil(lines.length / 80), Math.ceil(content.length / 6_000)),
  );
  const linesPerRange = Math.max(1, Math.ceil(lines.length / desiredRanges));
  const summaries: string[] = [];
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
    `Read exact lines with forge_expand_output(handle=\"${handle}\", start_line=N, end_line=M).`,
    `Search without reading everything with forge_expand_output(handle=\"${handle}\", query=\"text\").`,
  ].join("\n");
}

export class ToolOutputCompactor {
  private readonly root: string;
  private readonly largeOutputChars: number;
  private readonly maxSummaryRanges: number;
  private readonly maxExpandLines: number;
  private readonly maxExpandChars: number;

  constructor(
    root = join(runtimeRoot(), "tool-results"),
    largeOutputChars = 8_000,
    maxSummaryRanges = 20,
    maxExpandLines = 240,
    maxExpandChars = 64_000,
  ) {
    this.root = root;
    this.largeOutputChars = largeOutputChars;
    this.maxSummaryRanges = maxSummaryRanges;
    this.maxExpandLines = maxExpandLines;
    this.maxExpandChars = maxExpandChars;
  }

  shouldCompact(content: string): boolean {
    return content.length > this.largeOutputChars;
  }

  async compact(sessionId: string, toolName: string, content: string): Promise<CompactResult | null> {
    if (!this.shouldCompact(content)) return null;
    if (!sessionId) throw new Error("session_id is required for compacted output");

    await mkdir(this.root, { recursive: true, mode: 0o700 });
    const handle = `fo_${randomBytes(16).toString("hex")}`;
    const sanitized = redact(content);
    const metadata: StoredMetadata = {
      schema_version: 1,
      handle,
      session_id: sessionId,
      tool_name: toolName,
      chars: sanitized.length,
      line_count: splitLines(sanitized).length,
      sha256: createHash("sha256").update(sanitized).digest("hex"),
    };
    await Promise.all([
      writeFile(this.rawPath(handle), sanitized, { encoding: "utf8", mode: 0o600, flag: "wx" }),
      writeFile(this.metadataPath(handle), JSON.stringify(metadata), { encoding: "utf8", mode: 0o600, flag: "wx" }),
    ]);
    return {
      ...metadata,
      replacement_output: buildSummary(handle, toolName, sanitized, this.maxSummaryRanges),
    };
  }

  async expand(sessionId: string, handle: string, startLine = 1, endLine?: number): Promise<Expansion> {
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
      truncated,
    };
  }

  async search(sessionId: string, handle: string, query: string, contextLines = 2): Promise<SearchResult> {
    if (!query.trim()) throw new Error("query must be non-empty");
    if (!Number.isInteger(contextLines) || contextLines < 0 || contextLines > 10) {
      throw new Error("context_lines must be between 0 and 10");
    }
    const { lines } = await this.loadOwned(sessionId, handle);
    const needle = query.toLowerCase();
    const indexes = lines
      .map((line, index) => (line.toLowerCase().includes(needle) ? index : -1))
      .filter((index) => index >= 0);
    const matches: SearchResult["matches"] = [];
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
        content,
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
      truncated: characterLimited || indexes.length > matches.length,
    };
  }

  private async loadOwned(sessionId: string, handle: string): Promise<{
    metadata: StoredMetadata;
    content: string;
    lines: string[];
  }> {
    if (!HANDLE.test(handle)) throw new Error("malformed compacted-output handle");
    const metadataPath = this.metadataPath(handle);
    this.assertSafePath(metadataPath);
    const metadata = JSON.parse(await readFile(metadataPath, "utf8")) as StoredMetadata;
    if (metadata.handle !== handle || metadata.schema_version !== 1) {
      throw new Error("compacted-output metadata mismatch");
    }
    if (metadata.session_id !== sessionId) {
      throw new Error("compacted output belongs to another session");
    }
    const rawPath = this.rawPath(handle);
    this.assertSafePath(rawPath);
    const content = await readFile(rawPath, "utf8");
    if (createHash("sha256").update(content).digest("hex") !== metadata.sha256) {
      throw new Error("compacted output failed integrity verification");
    }
    return { metadata, content, lines: splitLines(content) };
  }

  private assertSafePath(path: string): void {
    if (lstatSync(path).isSymbolicLink()) throw new Error("unsafe compacted-output path");
    if (dirname(realpathSync(path)) !== realpathSync(this.root)) {
      throw new Error("unsafe compacted-output path");
    }
  }

  private rawPath(handle: string): string {
    return join(this.root, `${handle}.raw`);
  }

  private metadataPath(handle: string): string {
    return join(this.root, `${handle}.json`);
  }
}
