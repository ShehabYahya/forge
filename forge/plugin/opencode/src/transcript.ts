import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";

const MAX_TEST_OUTPUT_CHARS = 16_000;

const TEST_PATTERNS: RegExp[] = [
  /^pytest/,
  /^python\b.*\b(?:-m\s+)?pytest/,
  /^npm\s+(?:run\s+)?test/,
  /^node\s+--test/,
  /^cargo\s+test/,
  /^go\s+test/,
  /^make\s+test/,
  /^tox/,
  /^(?:pdm|uv|pipenv)\s+(?:run\s+)?pytest/,
  /^python\b.*\s+-m\s+unittest/,
  /^django\s+test/,
  /^rake\s+test/,
  /^mvn\s+test/,
  /^gradle\s+test/,
  /^dotnet\s+test/,
  /^jest\b/,
  /^vitest\b/,
  /^bun\s+test/,
  /^deno\s+test/,
];

function isTestCommand(command: string): boolean {
  return TEST_PATTERNS.some((p) => p.test(command.trim()));
}

const MUTATION_CAPABLE_PATTERNS: RegExp[] = [
  /sed\s.*-i/,
  />\s*\S/,
  />>/,
  /2>\s*\S/,
  /&>\s*\S/,
  /\btee\b/,
  /\btouch\b/,
  /\bmkdir\b/,
  /\brm\b/,
  /\bmv\b/,
  /\bcp\b/,
  /\bgit\s+apply\b/,
  /\bgit\s+checkout\b/,
  /\bgit\s+reset\b/,
  /\bgit\s+clean\b/,
  /\b(?:npm|pnpm|yarn)\s+install\b/,
  /\b(?:python|python3|node|deno|ruby|perl)\s+\S*(?:script|generate|build|setup|install|migrate|seed|deploy|update)[^/\s]*\.(?:py|js|ts|rb|pl|sh)\b/,
];

function classifyMutationRisk(command: string): boolean {
  const trimmed = command.trim();
  return MUTATION_CAPABLE_PATTERNS.some((p) => p.test(trimmed));
}

function extractExitCode(metadata: unknown): number | null {
  if (!metadata || typeof metadata !== "object") return null;
  const m = metadata as Record<string, unknown>;
  for (const key of ["exitCode", "exit_code", "code"]) {
    const val = m[key];
    if (typeof val === "number" && Number.isInteger(val)) return val;
  }
  return null;
}

function outsideWorktree(relPath: string): boolean {
  return relPath === ".." || relPath.startsWith(`..${sep}`) || isAbsolute(relPath);
}

function portablePath(path: string): string {
  return path.split(sep).join("/");
}

type ResolvedToolPath = {
  sessionPath: string;
  fsPath: string;
  inWorktree: boolean;
};

export type FileDigestEntry = {
  path: string;
  kind: "file" | "missing" | "symlink" | "unreadable";
  sha256: string | null;
};

export type TestRun = {
  command: string;
  output: string;
  exit_code: number | null;
};

export type MutationCaptureStatus =
  | "no_mutation_risk"
  | "captured_mutation"
  | "possible_uncaptured_mutation";

export type SessionDigest = {
  edited_files: string[];
  edited_files_digest: string;
  digest_version: number;
  test_runs: TestRun[];
  mutation_status: MutationCaptureStatus;
};

export class TranscriptDigester {
  private worktree: string | null;
  private filesBySession = new Map<string, Set<string>>();
  private editSequenceBySession = new Map<string, string[]>();
  private testsBySession = new Map<string, TestRun[]>();
  private mutationStatusBySession = new Map<string, MutationCaptureStatus>();

  constructor(worktree: string | null = null) {
    this.worktree = worktree;
  }

  after(
    sessionID: string,
    tool: string,
    args: Record<string, unknown>,
    output: string,
    metadata?: unknown,
  ): void {
    try {
      const safeArgs = args && typeof args === "object" ? args : {};
      if (tool === "edit" || tool === "write") {
        const filePath = typeof safeArgs.filePath === "string"
          ? safeArgs.filePath
          : typeof safeArgs.path === "string"
            ? safeArgs.path
            : null;
        if (!filePath) return;
        let files = this.filesBySession.get(sessionID);
        if (!files) {
          files = new Set();
          this.filesBySession.set(sessionID, files);
        }
        const sessionPath = this._resolveToolPath(filePath).sessionPath;
        files.add(sessionPath);
        let editSequence = this.editSequenceBySession.get(sessionID);
        if (!editSequence) {
          editSequence = [];
          this.editSequenceBySession.set(sessionID, editSequence);
        }
        editSequence.push(sessionPath);
        this.mutationStatusBySession.set(sessionID, "captured_mutation");
        return;
      }
      if (tool === "bash") {
        const command = typeof safeArgs.command === "string" ? safeArgs.command : "";
        if (!command) return;

        if (classifyMutationRisk(command)) {
          const current = this.mutationStatusBySession.get(sessionID);
          if (current !== "captured_mutation") {
            this.mutationStatusBySession.set(sessionID, "possible_uncaptured_mutation");
          }
        }

        if (!isTestCommand(command)) return;
        let tests = this.testsBySession.get(sessionID);
        if (!tests) {
          tests = [];
          this.testsBySession.set(sessionID, tests);
        }
        tests.push({
          command,
          output: output.slice(0, MAX_TEST_OUTPUT_CHARS),
          exit_code: extractExitCode(metadata),
        });
      }
    } catch {
    }
  }

  flush(sessionID: string): SessionDigest {
    const files = [...(this.filesBySession.get(sessionID) ?? [])].sort();
    const editSequence = this.editSequenceBySession.get(sessionID) ?? [];
    let edited_files_digest: string;
    let digest_version: number;

    if (this.worktree) {
      digest_version = 2;
      const entries = files
        .map((f) => this._fileDigestEntry(f))
        .sort((a, b) => a.path.localeCompare(b.path));
      edited_files_digest = createHash("sha256")
        .update(JSON.stringify({
          edit_sequence: editSequence,
          file_entries: entries,
        }))
        .digest("hex");
    } else {
      // v1 fallback: edit-sequence-based digest (no worktree available).
      // This detects same-file re-edits via sequence length but cannot
      // detect external content mutations or edit-then-revert.
      digest_version = 1;
      const hash = createHash("sha256");
      for (const path of editSequence) {
        const value = Buffer.from(path, "utf8");
        const length = Buffer.alloc(8);
        length.writeBigUInt64BE(BigInt(value.length));
        hash.update(length);
        hash.update(value);
      }
      edited_files_digest = hash.digest("hex");
    }
    return {
      edited_files: files,
      edited_files_digest,
      digest_version,
      test_runs: [...(this.testsBySession.get(sessionID) ?? [])],
      mutation_status: this.mutationStatusBySession.get(sessionID) ?? "no_mutation_risk",
    };
  }

  /**
   * Compute a per-file content digest entry for the content-aware session
   * digest (v2). Normalizes absolute paths to repo-relative, detects
   * file/missing/symlink/unreadable state, and hashes file bytes for
   * regular files. Symlinks are never followed (security: could point
   * outside the repo). Unreadable/missing files produce deterministic
   * kind markers so the digest cannot silently claim freshness.
   */
  private _resolveToolPath(rawPath: string): ResolvedToolPath {
    if (!this.worktree) {
      return { sessionPath: rawPath, fsPath: rawPath, inWorktree: true };
    }
    const fsPath = isAbsolute(rawPath)
      ? resolve(rawPath)
      : resolve(this.worktree, rawPath);
    const relPath = relative(this.worktree, fsPath);
    if (outsideWorktree(relPath)) {
      return { sessionPath: rawPath, fsPath, inWorktree: false };
    }
    return {
      sessionPath: portablePath(relPath || "."),
      fsPath,
      inWorktree: true,
    };
  }

  private _fileDigestEntry(rawPath: string): FileDigestEntry {
    const resolved = this._resolveToolPath(rawPath);
    if (!resolved.inWorktree) {
      return { path: resolved.sessionPath, kind: "unreadable", sha256: null };
    }
    const relPath = resolved.sessionPath;
    try {
      const stat = lstatSync(resolved.fsPath);
      if (stat.isSymbolicLink()) {
        return { path: relPath, kind: "symlink", sha256: null };
      }
      if (!stat.isFile()) {
        return { path: relPath, kind: "unreadable", sha256: null };
      }
      try {
        const content = readFileSync(resolved.fsPath);
        return {
          path: relPath,
          kind: "file",
          sha256: createHash("sha256").update(content).digest("hex"),
        };
      } catch {
        return { path: relPath, kind: "unreadable", sha256: null };
      }
    } catch {
      return { path: relPath, kind: "missing", sha256: null };
    }
  }

  clear(sessionID: string): void {
    this.filesBySession.delete(sessionID);
    this.editSequenceBySession.delete(sessionID);
    this.testsBySession.delete(sessionID);
    this.mutationStatusBySession.delete(sessionID);
  }
}
