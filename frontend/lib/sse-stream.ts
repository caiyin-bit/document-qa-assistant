export type ServerEvent =
  | { type: "text"; delta: string }
  | { type: "tool_call_started"; id: string; name: string }
  | { type: "tool_call_finished"; id: string; ok: boolean }
  | { type: "done" }
  | { type: "error"; message: string; code: string };

export async function* parseSSE(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<ServerEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const ev = parseBlock(block);
        if (ev) yield ev;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseBlock(block: string): ServerEvent | null {
  let eventType = "message";
  let dataLine = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
  }
  if (!dataLine) return null;
  let data: unknown;
  try {
    data = JSON.parse(dataLine);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const d = data as Record<string, unknown>;
  switch (eventType) {
    case "text":
      return { type: "text", delta: String(d.delta ?? "") };
    case "tool_call_started":
      return {
        type: "tool_call_started",
        id: String(d.id),
        name: String(d.name),
      };
    case "tool_call_finished":
      return {
        type: "tool_call_finished",
        id: String(d.id),
        ok: !!d.ok,
      };
    case "done":
      return { type: "done" };
    case "error":
      return {
        type: "error",
        message: String(d.message ?? ""),
        code: String(d.code ?? "error"),
      };
    default:
      return null;
  }
}
