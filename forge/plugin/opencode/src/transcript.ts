import { createHash } from "node:crypto";

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

export type SessionDigest = {
  edited_files: string[];
  edited_files_digest: string;
  test_runs: Array<{ command: string; output: string }>;
};

export class TranscriptDigester {
  private filesBySession = new Map<string, Set<string>>();
  private testsBySession = new Map<string, Array<{ command: string; output: string }>>();

  /**
   * Accumulate evidence from a tool call. Called on every tool.execute.after.
   *
   * - edit / write  → records the file path in edited_files (deduplicated Set).
   * - bash          → if the command matches a test-runner pattern, records
   *                    {command, output} with output capped at 16 000 chars.
   * - all others    → discard.
   *
   * Wrapped entirely in try/catch so a bug in evidence extraction never blocks
   * the tool.execute.after hook (which is on the compaction critical path).
   */
  after(sessionID: string, tool: string, args: Record<string, unknown>, output: string): void {
    try {
      if (tool === "edit" || tool === "write") {
        const filePath = typeof args.filePath === "string"
          ? args.filePath
          : typeof args.path === "string"
            ? args.path
            : null;
        if (!filePath) return;
        let files = this.filesBySession.get(sessionID);
        if (!files) {
          files = new Set();
          this.filesBySession.set(sessionID, files);
        }
        files.add(filePath);
        return;
      }
      if (tool === "bash") {
        const command = typeof args.command === "string" ? args.command : "";
        if (!command) return;
        if (!isTestCommand(command)) return;
        let tests = this.testsBySession.get(sessionID);
        if (!tests) {
          tests = [];
          this.testsBySession.set(sessionID, tests);
        }
        tests.push({ command, output: output.slice(0, MAX_TEST_OUTPUT_CHARS) });
      }
    } catch {
      // Never let evidence extraction block the hook.
    }
  }

  /**
   * Return a snapshot of cumulative evidence for the session. Does NOT clear
   * the accumulators — edited_files is a Set (naturally deduplicated on
   * re-insert) and test_runs is a growing log. Multiple review_changes calls
   * in the same session each get an up-to-date snapshot.
   *
   * edited_files_digest is SHA256 over sorted unique file paths, used by the
   * backend for per-session staleness checks.
   */
  flush(sessionID: string): SessionDigest {
    const files = [...(this.filesBySession.get(sessionID) ?? [])].sort();
    const edited_files_digest = createHash("sha256")
      .update(files.join("\n"))
      .digest("hex");
    return {
      edited_files: files,
      edited_files_digest,
      test_runs: [...(this.testsBySession.get(sessionID) ?? [])],
    };
  }

  clear(sessionID: string): void {
    this.filesBySession.delete(sessionID);
    this.testsBySession.delete(sessionID);
  }
}
