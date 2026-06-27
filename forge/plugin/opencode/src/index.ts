import { readFile, realpath } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { type Plugin, tool } from "@opencode-ai/plugin";
import { ToolOutputCompactor } from "./compaction.ts";
import { ContextGovernor } from "./governor.ts";
import {
  forgeSystemBlock,
  hasForgeSystemMarker,
} from "./forge-system.ts";
import {
  FORGE_FINISH_TOOL,
  installReviewMemoryCommand,
  MAINTENANCE_TOOL,
  MemoryMaintenanceAdapter,
} from "./maintenance.ts";
import { BridgeClient } from "./transport.ts";
import { TranscriptDigester } from "./transcript.ts";

const DEFAULT_FORGE_MCP_KEY = "forge";
const FORGE_MCP_READINESS_MS = 3000;
const FORGE_MCP_POLL_INTERVAL_MS = 100;

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

function extractSessionID(properties: unknown): string | null {
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return null;
  const values = properties as Record<string, unknown>;
  if (typeof values.sessionID === "string" && values.sessionID) return values.sessionID;
  const info = values.info;
  if (info && typeof info === "object" && !Array.isArray(info)) {
    const id = (info as Record<string, unknown>).id;
    if (typeof id === "string" && id) return id;
  }
  return null;
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
  installReviewMemoryCommand(config);
}

function resolveForgeExecutable(): string {
  try {
    const pluginDir = dirname(fileURLToPath(import.meta.url));
    const root = dirname(dirname(dirname(dirname(pluginDir))));
    return join(root, ".venv", "bin", "forge");
  } catch {
    return "forge";
  }
}

function addForgeMcpConfig(config: Record<string, unknown>, forgeMcpKey: string): void {
  const existing = config.mcp && typeof config.mcp === "object"
    ? config.mcp as Record<string, unknown>
    : {};

  const existingEntry = existing[forgeMcpKey];
  if (existingEntry && typeof existingEntry === "object" && !Array.isArray(existingEntry)) {
    const state = (existingEntry as Record<string, unknown>).state;
    if (state === "disabled" || state === "deny") return;
    if ((existingEntry as Record<string, unknown>).command !== undefined) return;
    if ((existingEntry as Record<string, unknown>).url !== undefined) return;
  }

  /**
   * FORGE_EXECUTABLE / FORGE_ALPHA_EXECUTABLE — override the path to the
   * Forge executable binary. FORGE_EXECUTABLE takes precedence; if unset,
   * FORGE_ALPHA_EXECUTABLE is checked. When both are unset, the plugin
   * auto-detects the executable via resolveForgeExecutable().
   */
  const executable = process.env.FORGE_EXECUTABLE?.trim()
    || process.env.FORGE_ALPHA_EXECUTABLE?.trim()
    || resolveForgeExecutable();
  const next = { ...existing };
  delete next["forge"];

  config.mcp = {
    ...next,
    [forgeMcpKey]: {
      type: "local",
      command: [executable, "mcp"],
      enabled: true,
    },
  };
}

async function compactTextResult(
  compactor: ToolOutputCompactor,
  sessionId: string,
  toolName: string,
  output: Record<string, unknown>,
): Promise<void> {
  if (typeof output.output === "string") {
    const metadata = output.metadata as Record<string, unknown> | undefined;
    const source = await recoverFullOutput(output);
    if (!source && metadata?.truncated === true) return;
    const toCompact = source ?? output.output;
    const compacted = await compactor.compact(sessionId, toolName, toCompact);
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

function resolveForgeMcpKey(options: Record<string, unknown> | undefined): string {
  const fromOpt = options && typeof options.forgeMcpKey === "string" && options.forgeMcpKey.trim()
    ? options.forgeMcpKey.trim() : "";
  const fromEnv = process.env.FORGE_MCP_KEY?.trim() || "";
  return fromOpt || fromEnv || DEFAULT_FORGE_MCP_KEY;
}

function resolveForgeMcpReadinessMs(options: Record<string, unknown> | undefined): number {
  const fromOpt = options && typeof options.forgeMcpReadinessMs === "number" && options.forgeMcpReadinessMs > 0
    ? options.forgeMcpReadinessMs : 0;
  const fromEnv = Number(process.env.FORGE_MCP_READINESS_MS);
  return fromOpt || (Number.isFinite(fromEnv) && fromEnv > 0 ? fromEnv : FORGE_MCP_READINESS_MS);
}

export async function getForgeMcpStatus(
  client: { mcp: { status: () => Promise<unknown> } },
  forgeMcpKey: string,
): Promise<string | undefined> {
  let result: unknown;
  try {
    result = await client.mcp.status();
  } catch {
    return undefined;
  }
  const servers = (result as { data?: Record<string, { status?: string }> } | undefined)?.data;
  return servers?.[forgeMcpKey]?.status;
}

export async function waitForForgeMcpConnected(
  client: { mcp: { status: () => Promise<unknown> } },
  forgeMcpKey: string,
  deadlineMs: number = FORGE_MCP_READINESS_MS,
): Promise<boolean> {
  const deadline = Date.now() + deadlineMs;
  while (Date.now() < deadline) {
    const status = await getForgeMcpStatus(client, forgeMcpKey);
    if (status === "connected") return true;
    if (status === "disabled" || status === "failed"
        || status === "needs_auth" || status === "needs_client_registration") {
      return false;
    }
    await new Promise((r) => setTimeout(r, FORGE_MCP_POLL_INTERVAL_MS));
  }
  return false;
}

export const ForgeAlphaPlugin: Plugin = async ({ client, worktree }, options) => {
  if (!worktree) return {};

  const governor = new ContextGovernor("active", worktree, {
    can_block_before: true,
    can_replace_output: true,
    can_request_confirmation: true,
  });
  const compactor = new ToolOutputCompactor();
  const bridge = new BridgeClient();
  const digester = new TranscriptDigester();
  const maintenance = new MemoryMaintenanceAdapter(client, bridge);
  const forgeMcpKey = resolveForgeMcpKey(options as Record<string, unknown> | undefined);
  const forgeMcpReadinessMs = resolveForgeMcpReadinessMs(options as Record<string, unknown> | undefined);

  /** Tracks active sessions so the shared bridge is only closed when the last session exits. */
  let sessionCount = 0;

  return {
    config: async (config) => {
      applyForgePermissions(config as unknown as Record<string, unknown>);
      addForgeMcpConfig(config as unknown as Record<string, unknown>, forgeMcpKey);
    },

    "experimental.chat.system.transform": async (_input, output) => {
      if (!Array.isArray(output.system) || output.system.length === 0) return;
      const first = output.system[0];
      if (typeof first !== "string") return;
      if (hasForgeSystemMarker(first)) return;

      const connected = await waitForForgeMcpConnected(client, forgeMcpKey, forgeMcpReadinessMs);
      if (!connected) return;

      output.system[0] = `${first}\n\n${forgeSystemBlock()}`;
    },

    event: async ({ event }) => {
      const sessionId = extractSessionID(event.properties);
      if (event.type === "session.created" && sessionId) {
        sessionCount = Math.max(0, sessionCount) + 1;
      }
      if (event.type === "session.deleted") {
        if (sessionId) {
          governor.clearSession(sessionId);
          maintenance.clear(sessionId);
          digester.clear(sessionId);
        }
        sessionCount = Math.max(0, sessionCount - 1);
        if (sessionCount <= 0) {
          bridge.close();
        }
        return;
      }
      if ((event.type === "session.created" || event.type === "session.idle") && sessionId) {
        await maintenance.recommend(sessionId);
      }
      if (event.type === "session.created" && sessionId) {
        await maintenance.checkUpdate(sessionId);
      }
    },

    "tool.execute.before": async (input, output) => {
      // Clear digest accumulator on new-task start to prevent cross-task
      // contamination when sequential tasks share the same session.
      if (input.tool === "start_task") {
        digester.clear(input.sessionID);
      }

      // Flush and push transcript digest to the backend BEFORE the MCP tool
      // executes so the backend can consume it during finish_task / review_changes.
      if (input.tool === "finish_task" || input.tool === "review_changes") {
        const digest = digester.flush(input.sessionID);
        try {
          await bridge.request("session_digest", {
            host_session_id: input.sessionID,
            digest,
          });
        } catch {
          // Bridge push is advisory; on failure, the backend falls back
          // to git-based behavior. Never block the tool.
        }
      }

      if (await maintenance.before(input.sessionID, input.tool)) return;

      const result = governor.before(input.sessionID, input.tool, output.args ?? {});
      if (result.decision === "block") throw new Error(`Forge: ${result.reason}`);
      if (result.decision !== "warn" && result.decision !== "escalate") return;
      try {
        await client.tui.showToast({
          body: {
            message: result.decision === "escalate"
              ? `Forge: approval required - ${result.reason}`
              : `Forge: ${result.reason}`,
            variant: "warning",
          },
        });
      } catch {
        // The native permission prompt remains authoritative when no TUI is attached.
      }
    },

    "tool.execute.after": async (input, output) => {
      // Accumulate transcript evidence before compaction mutates output.
      // Note: input.args is the correct source; output has {title, output, metadata}.
      digester.after(
        input.sessionID,
        input.tool,
        input.args ?? {},
        typeof (output as Record<string, unknown>).output === "string"
          ? (output as Record<string, unknown>).output as string
          : "",
      );

      if (input.tool === "forge_expand_output"
          || maintenance.exemptFromCompaction(input.sessionID, input.tool)) return;
      try {
        await compactTextResult(
          compactor,
          input.sessionID,
          input.tool,
          output as unknown as Record<string, unknown>,
        );
      } catch {
        // Compaction is advisory; failure (disk full, permissions, etc.)
        // must not crash the tool-execution pipeline.
      }
      if (input.tool === FORGE_FINISH_TOOL) {
        await maintenance.recommend(input.sessionID);
      }
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

      [MAINTENANCE_TOOL]: maintenance.tool(),
    },
  };
};

export default ForgeAlphaPlugin;
