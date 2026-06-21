import { type Plugin, tool } from "@opencode-ai/plugin";
import { readFile, realpath } from "node:fs/promises";
import { homedir } from "node:os";
import { isAbsolute, join, relative } from "node:path";
import { ToolOutputCompactor } from "./compaction.ts";
import { ContextGovernor } from "./governor.ts";

type PermissionAction = "allow" | "ask" | "deny";
type PermissionRules = Record<string, PermissionAction>;

export const DANGEROUS_BASH_PERMISSION_PATTERNS = [
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
  "git * push *--force*",
] as const;

function withDangerousAsks(existing: unknown): PermissionAction | PermissionRules {
  if (existing === "deny") return "deny";
  const configured = existing && typeof existing === "object" ? existing as PermissionRules : {};
  const fallback = typeof existing === "string" ? existing as PermissionAction : configured["*"] ?? "allow";
  const rules: PermissionRules = { "*": fallback, ...configured };
  for (const pattern of DANGEROUS_BASH_PERMISSION_PATTERNS) {
    if (configured[pattern] !== "deny") rules[pattern] = "ask";
  }
  return rules;
}

export function applyForgePermissions(config: Record<string, unknown>): void {
  const existing = config.permission && typeof config.permission === "object"
    ? config.permission as Record<string, unknown>
    : {};
  config.permission = {
    ...existing,
    bash: withDangerousAsks(existing.bash),
    external_directory: existing.external_directory === "deny" ? "deny" : "ask",
  };
}

async function compactTextResult(
  compactor: ToolOutputCompactor,
  sessionId: string,
  toolName: string,
  output: Record<string, unknown>,
): Promise<void> {
  if (typeof output.output === "string") {
    const source = await recoverFullOutput(output) ?? output.output;
    const compacted = await compactor.compact(sessionId, toolName, source);
    if (compacted) output.output = compacted.replacement_output;
    return;
  }

  if (!Array.isArray(output.content)) return;
  for (const item of output.content) {
    if (!item || typeof item !== "object") continue;
    const content = item as Record<string, unknown>;
    if (content.type !== "text" || typeof content.text !== "string") continue;
    const compacted = await compactor.compact(sessionId, toolName, content.text);
    if (compacted) content.text = compacted.replacement_output;
  }
}

async function recoverFullOutput(output: Record<string, unknown>): Promise<string | null> {
  const metadata = output.metadata;
  if (!metadata || typeof metadata !== "object") return null;
  const values = metadata as Record<string, unknown>;
  if (values.truncated !== true || typeof values.outputPath !== "string") return null;

  try {
    const dataRoot = process.env.XDG_DATA_HOME?.trim() || join(homedir(), ".local", "share");
    const allowedRoot = await realpath(join(dataRoot, "opencode", "tool-output"));
    const candidate = await realpath(values.outputPath);
    const rel = relative(allowedRoot, candidate);
    if (rel === ".." || rel.startsWith(`..${process.platform === "win32" ? "\\" : "/"}`) || isAbsolute(rel)) {
      return null;
    }
    return await readFile(candidate, "utf8");
  } catch {
    return null;
  }
}

export const ForgeAlphaPlugin: Plugin = async ({ client, worktree }) => {
  if (!worktree) return {};

  const governor = new ContextGovernor("active", worktree, {
    can_block_before: true,
    can_replace_output: true,
    can_request_confirmation: true,
  });
  const compactor = new ToolOutputCompactor();

  return {
    config: async (config) => {
      applyForgePermissions(config as unknown as Record<string, unknown>);
    },

    event: async ({ event }) => {
      if (event.type !== "session.deleted") return;
      const properties = event.properties as { info?: { id?: string }; sessionID?: string };
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
            message: result.decision === "escalate"
              ? `Forge Alpha: approval required - ${result.reason}`
              : `Forge Alpha: ${result.reason}`,
            variant: "warning",
          },
        });
      } catch {
        // The native permission prompt remains authoritative when no TUI is attached.
      }
    },

    "tool.execute.after": async (input, output) => {
      if (input.tool === "forge_expand_output") return;
      await compactTextResult(
        compactor,
        input.sessionID,
        input.tool,
        output as unknown as Record<string, unknown>,
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
          context_lines: tool.schema.number().int().min(0).max(10).optional(),
        },
        async execute(args, context) {
          if (args.query) {
            const result = await compactor.search(
              context.sessionID,
              args.handle,
              args.query,
              args.context_lines ?? 2,
            );
            return JSON.stringify(result, null, 2);
          }
          const result = await compactor.expand(
            context.sessionID,
            args.handle,
            args.start_line ?? 1,
            args.end_line,
          );
          return [
            `[${result.handle} L${result.start_line}-L${result.end_line} of ${result.total_lines}]`,
            result.content,
            result.truncated ? "[Character limit reached; request a smaller line range.]" : "",
          ].filter(Boolean).join("\n");
        },
      }),
    },
  };
};

export default ForgeAlphaPlugin;
