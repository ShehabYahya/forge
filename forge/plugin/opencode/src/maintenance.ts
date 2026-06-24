import { tool } from "@opencode-ai/plugin";
import { BridgeClient, type BridgeResponse } from "./transport.ts";

export const MAINTENANCE_TOOL = "forge_memory_review";
export const FORGE_FINISH_TOOL = "finish_task";

const REVIEW_MEMORY_TEMPLATE = `Enter Forge memory review mode for this session.

Use the forge_memory_review tool to start, read context, apply a small validated batch, re-read context, and finish. Do not use edit, write, or bash. If a maintenance call fails, retry once; if it fails again, explain the failure and finish with status failed and a concrete reason.

Check \`memory_gaps\` in the context for completed or failed tasks that have no memory card. For each gap with a reusable lesson, use \`create_memory_card\` (1 source task). Each operation entry must include a non-empty \`temp_id\` field and use field names \`memory\` (not \`memory_text\`) and \`source_task_ids\` (a list, not a single string). Example: {"operation": "create_memory_card", "temp_id": "...", "memory": "... (40-400 chars, concrete anchor like file path or tool name)", "why": "... (20+ chars)", "source_task_ids": ["task_id"]}. For cross-task patterns spanning 2+ tasks, use \`create_pattern_card\`.`;

type ToastClient = {
  tui: { showToast(value: { body: { message: string; variant: "warning" } }): Promise<unknown> };
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function payloadRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function parseOperationsJSON(input: string): Record<string, unknown>[] {
  const parsed = JSON.parse(input);
  if (!Array.isArray(parsed)) throw new Error("operations_json must decode to a JSON array");
  return parsed.filter(isRecord);
}

export function installReviewMemoryCommand(config: Record<string, unknown>): void {
  const commands = isRecord(config.command) ? config.command : {};
  config.command = {
    ...commands,
    "review-memory": {
      template: REVIEW_MEMORY_TEMPLATE,
      description: "Review Forge memory cards for the current session",
    },
  };
}

export class MemoryMaintenanceAdapter {
  private readonly activeSessions = new Set<string>();
  private readonly sessionEpoch = new Map<string, number>();
  private readonly client: ToastClient;
  private readonly bridge: BridgeClient;

  constructor(client: ToastClient, bridge: BridgeClient) {
    this.client = client;
    this.bridge = bridge;
  }

  private async request(
    operation: string,
    sessionID: string,
    payload: Record<string, unknown> = {},
  ): Promise<BridgeResponse> {
    const base: Record<string, unknown> = { host_session_id: sessionID };
    const epoch = this.sessionEpoch.get(sessionID);
    if (epoch !== undefined) {
      base.epoch = epoch;
    }
    return await this.bridge.request(operation, { ...base, ...payload });
  }

  private async context(sessionID: string): Promise<Record<string, unknown> | null> {
    const response = await this.request("get_maintenance_context", sessionID);
    const payload = payloadRecord(response.payload);
    if (!response.ok || payload.mode !== "memory_review") {
      this.activeSessions.delete(sessionID);
      this.sessionEpoch.delete(sessionID);
      return null;
    }
    this.activeSessions.add(sessionID);
    return payload;
  }

  async before(sessionID: string, toolName: string): Promise<boolean> {
    if (toolName === MAINTENANCE_TOOL) return true;
    if (!this.activeSessions.has(sessionID)) return false;
    let context: Record<string, unknown> | null;
    try {
      context = await this.context(sessionID);
    } catch {
      throw new Error("Forge: maintenance bridge unavailable; exit /review-memory and retry");
    }
    const allowed = new Set(
      Array.isArray(context?.allowed_tools)
        ? context.allowed_tools.filter((value): value is string => typeof value === "string")
        : [],
    );
    if (!allowed.has(toolName)) {
      throw new Error("Forge: not allowed in maintenance mode; exit /review-memory first");
    }
    return true;
  }

  exemptFromCompaction(sessionID: string, toolName: string): boolean {
    return toolName === MAINTENANCE_TOOL || this.activeSessions.has(sessionID);
  }

  async recommend(sessionID: string): Promise<void> {
    try {
      const response = await this.request("memory_maintenance_recommendation", sessionID);
      const payload = payloadRecord(response.payload);
      if (!response.ok || payload.recommend !== true || typeof payload.reason !== "string") return;
      await this.client.tui.showToast({
        body: { message: `Forge: ${payload.reason}. Run /review-memory.`, variant: "warning" },
      });
      await this.request("mark_recommendation_shown", sessionID, { reason: payload.reason });
    } catch {
      // Recommendations are advisory and must not break the host session.
    }
  }

  async checkUpdate(sessionID: string): Promise<void> {
    try {
      const response = await this.request("check_update", sessionID);
      const payload = payloadRecord(response.payload);
      if (!response.ok || payload.update_available !== true) return;
      const latest = typeof payload.latest_version === "string" ? payload.latest_version : "";
      const current = typeof payload.current_version === "string" ? payload.current_version : "";
      if (!latest) return;
      await this.client.tui.showToast({
        body: {
          message: `Forge ${latest} is available (you have ${current}). Run \`forge install\` to update.`,
          variant: "warning",
        },
      });
      await this.request("mark_update_shown", sessionID, { latest_version: latest });
    } catch {
      // Update checks are advisory and must not break the host session.
    }
  }

  clear(sessionID: string): void {
    this.activeSessions.delete(sessionID);
    this.sessionEpoch.delete(sessionID);
  }

  tool() {
    return tool({
      description: "Proxy Forge memory review operations through the hidden maintenance backend.",
      args: {
        action: tool.schema.string().describe("One of: start, context, apply_batch, finish, recommendation"),
        operations_json: tool.schema.string().optional().describe("For apply_batch: a JSON array of operation objects"),
        status: tool.schema.string().optional().describe("For finish: completed or failed"),
        reason: tool.schema.string().optional().describe("Optional finish failure/success reason"),
        force: tool.schema.boolean().optional().describe("For start: force-reclaim a live maintenance lock (requires config enable)"),
      },
      execute: async (args, context) => {
        const operations: Record<string, unknown> = { action: args.action };
        if (args.operations_json !== undefined) {
          operations.operations = parseOperationsJSON(args.operations_json);
        }
        if (args.status !== undefined) operations.status = args.status;
        if (args.reason !== undefined) operations.reason = args.reason;
        if (args.force !== undefined) operations.force = args.force;
        const response = await this.dispatch(context.sessionID, operations);
        if (!response.ok) {
          throw new Error(response.user_message || `Forge: ${response.reason || "maintenance request failed"}`);
        }
        return JSON.stringify(response.payload ?? {}, null, 2);
      },
    });
  }

  private async dispatch(sessionID: string, args: Record<string, unknown>): Promise<BridgeResponse> {
    const action = args.action;
    if (action === "start") {
      const payload: Record<string, unknown> = {};
      if (args.force !== undefined) payload.force = args.force;
      const response = await this.request("start_memory_maintenance", sessionID, payload);
      if (response.ok) {
        this.activeSessions.add(sessionID);
        const responsePayload = payloadRecord(response.payload);
        if (typeof responsePayload.epoch === "number") {
          this.sessionEpoch.set(sessionID, responsePayload.epoch);
        }
      }
      return response;
    }
    if (action === "context") return await this.request("get_maintenance_context", sessionID);
    if (action === "apply_batch") {
      const response = await this.request("apply_memory_review_batch", sessionID, {
        operations: args.operations ?? [],
      });
      const responsePayload = payloadRecord(response.payload);
      const leaseState = responsePayload.lease_state;
      if (!response.ok || (typeof leaseState === "string" && leaseState !== "active")) {
        this.activeSessions.delete(sessionID);
        this.sessionEpoch.delete(sessionID);
      }
      return response;
    }
    if (action === "finish") {
      const response = await this.request("finish_memory_maintenance", sessionID, {
        status: args.status ?? "completed",
        reason: args.reason ?? "",
      });
      this.activeSessions.delete(sessionID);
      this.sessionEpoch.delete(sessionID);
      return response;
    }
    if (action === "recommendation") {
      return await this.request("memory_maintenance_recommendation", sessionID);
    }
    throw new Error("Forge: unsupported memory review action");
  }
}
