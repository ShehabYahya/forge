import { tool } from "@opencode-ai/plugin";
import { BridgeClient, type BridgeResponse } from "./transport.ts";

export const MAINTENANCE_TOOL = "forge_memory_review";
export const FORGE_FINISH_TOOL = "finish_task";

const REVIEW_MEMORY_TEMPLATE = `Enter Forge memory review mode for this session.

Use the forge_memory_review tool to start, read context, apply a small validated batch, re-read context, and finish. Do not use edit, write, or bash. If a maintenance call fails, retry once; if it fails again, explain the failure and finish with status failed and a concrete reason.`;

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
  private readonly shownRecommendations = new Set<string>();
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
    return await this.bridge.request(operation, { host_session_id: sessionID, ...payload });
  }

  private async context(sessionID: string): Promise<Record<string, unknown> | null> {
    const response = await this.request("get_maintenance_context", sessionID);
    const payload = payloadRecord(response.payload);
    if (!response.ok || payload.mode !== "memory_review") {
      this.activeSessions.delete(sessionID);
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
      const key = `${sessionID}:${payload.reason}`;
      if (this.shownRecommendations.has(key)) return;
      this.shownRecommendations.add(key);
      await this.client.tui.showToast({
        body: { message: `Forge: ${payload.reason}. Run /review-memory.`, variant: "warning" },
      });
    } catch {
      // Recommendations are advisory and must not break the host session.
    }
  }

  clear(sessionID: string): void {
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
        reason: tool.schema.string().optional().describe("Optional finish failure/success reason"),
      },
      execute: async (args, context) => {
        const operations: Record<string, unknown> = { action: args.action };
        if (args.operations_json !== undefined) {
          operations.operations = parseOperationsJSON(args.operations_json);
        }
        if (args.status !== undefined) operations.status = args.status;
        if (args.reason !== undefined) operations.reason = args.reason;
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
      const response = await this.request("start_memory_maintenance", sessionID);
      if (response.ok) this.activeSessions.add(sessionID);
      return response;
    }
    if (action === "context") return await this.request("get_maintenance_context", sessionID);
    if (action === "apply_batch") {
      return await this.request("apply_memory_review_batch", sessionID, {
        operations: args.operations ?? [],
      });
    }
    if (action === "finish") {
      const response = await this.request("finish_memory_maintenance", sessionID, {
        status: args.status ?? "completed",
        reason: args.reason ?? "",
      });
      this.activeSessions.delete(sessionID);
      return response;
    }
    if (action === "recommendation") {
      return await this.request("memory_maintenance_recommendation", sessionID);
    }
    throw new Error("Forge: unsupported memory review action");
  }
}
