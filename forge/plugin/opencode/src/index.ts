import type { Plugin } from "@opencode-ai/plugin";
import { ContextGovernor } from "./governor.ts";

function permissionPattern(tool: string, args: Record<string, unknown>): string {
  if (tool === "bash" && typeof args.command === "string") {
    const first = args.command.split(/\s+/)[0] ?? "";
    return first ? `${first} *` : "bash *";
  }
  if (tool === "read" || tool === "write" || tool === "edit" || tool === "glob" || tool === "grep") {
    if (typeof args.filePath === "string") return args.filePath;
    if (typeof args.path === "string") return args.path;
    if (typeof args.pattern === "string") return args.pattern;
  }
  return `${tool} *`;
}

function formatDecision(
  decision: string,
  reason: string,
  tool: string,
  args: Record<string, unknown>,
): string {
  const pattern = permissionPattern(tool, args);
  const lines = [
    `Forge Alpha  ·  ${tool}`,
    `  Pattern: ${pattern}`,
    `  Reason: ${reason}`,
    "",
    `  [Deny]          — blocked by Forge Alpha`,
    `  [Allow Always]  — add "${pattern}": "allow" to opencode.json permissions`,
    `  [Allow Once]    — re-run the command`,
  ];
  return lines.join("\n");
}

export const ForgeAlphaPlugin: Plugin = async ({ client, worktree }) => {
  const repoRoot = worktree;
  if (!repoRoot) return {};

  const governor = new ContextGovernor("active", repoRoot, {
    can_block_before: true,
    can_replace_output: true,
    can_request_confirmation: true,
  });

  return {
    "tool.execute.before": async (
      input: { tool: string; sessionID?: string },
      output: { args: Record<string, unknown> },
    ) => {
      const sessionId = input.sessionID ?? repoRoot;
      const result = governor.before(sessionId, input.tool, output.args);

      if (result.decision === "block" || result.decision === "escalate") {
        throw new Error(formatDecision(
          result.decision,
          result.reason,
          input.tool,
          output.args,
        ));
      }

      if (result.decision === "warn" && result.reason) {
        try {
          await client.tui.showToast({
            body: { message: `Forge Alpha: ${result.reason}`, variant: "warning" },
          });
        } catch (e) {
          console.error("Forge Alpha toast failed:", e);
        }
      }
    },

    "tool.execute.after": async (
      input: { tool: string; sessionID?: string },
      output: { args: Record<string, unknown>; result?: string },
    ) => {
      const sessionId = input.sessionID ?? repoRoot;
      const result = governor.after(sessionId, input.tool, output.result ?? "");

      if (result.decision === "replace" && result.replacement_output) {
        output.result = result.replacement_output;
        return;
      }

      if (result.decision === "warn" && result.reason) {
        try {
          await client.tui.showToast({
            body: { message: `Forge Alpha: ${result.reason}`, variant: "warning" },
          });
        } catch (e) {
          console.error("Forge Alpha toast failed:", e);
        }
      }
    },
  };
};
