export async function sendToBackend(transport, operation, payload) {
  const wire = { schema_version: 1, operation, payload };
  const result = await transport(wire);
  if (!result || result.schema_version !== 1 || typeof result.ok !== "boolean") {
    throw new Error("invalid Forge Alpha backend response");
  }
  return result;
}

