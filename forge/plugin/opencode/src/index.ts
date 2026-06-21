import { sendToBackend } from "./transport.ts";

function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, child]) => [String(key), normalize(child)]));
  }
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) return value;
  return String(value);
}

export function createForgeAlphaAdapter(transport, display) {
  async function forward(operation, payload) {
    try {
      const result = await sendToBackend(transport, operation, normalize(payload));
      if (result.user_message) display(result.user_message);
      return result;
    } catch (error) {
      const degraded = {
        schema_version: 1,
        ok: false,
        task_id: null,
        decision: "warn",
        reason: `Forge Alpha backend unavailable: ${error.message}`,
        replacement_output: null,
        user_message: "Forge Alpha adapter is degraded; policy is not actively enforced.",
        capability_limited: true
      };
      display(degraded.user_message);
      return degraded;
    }
  }
  return {
    toolBefore: payload => forward("observe_tool_before", payload),
    toolAfter: payload => forward("observe_tool_after", payload),
    recordEvent: payload => forward("record_tool_event", payload),
    getActiveTask: payload => forward("get_active_task", payload)
  };
}

