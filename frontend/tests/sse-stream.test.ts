import { describe, expect, it } from "vitest";
import { parseSSE, type ServerEvent } from "@/lib/sse-stream";

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<ServerEvent[]> {
  const out: ServerEvent[] = [];
  for await (const ev of parseSSE(stream)) out.push(ev);
  return out;
}

describe("parseSSE", () => {
  it("parses 3 text deltas + done into 4 events in order", async () => {
    const stream = streamFromChunks([
      `event: text\ndata: {"delta":"你好"}\n\n`,
      `event: text\ndata: {"delta":"世界"}\n\n`,
      `event: text\ndata: {"delta":"!"}\n\n`,
      `event: done\ndata: {}\n\n`,
    ]);
    const out = await collect(stream);
    expect(out).toEqual([
      { type: "text", delta: "你好" },
      { type: "text", delta: "世界" },
      { type: "text", delta: "!" },
      { type: "done" },
    ]);
  });

  it("parses tool_call_started + tool_call_finished(ok=true) round trip", async () => {
    const stream = streamFromChunks([
      `event: tool_call_started\ndata: {"id":"tc1","name":"create_contact"}\n\n`,
      `event: tool_call_finished\ndata: {"id":"tc1","ok":true}\n\n`,
      `event: done\ndata: {}\n\n`,
    ]);
    const out = await collect(stream);
    expect(out).toEqual([
      { type: "tool_call_started", id: "tc1", name: "create_contact" },
      { type: "tool_call_finished", id: "tc1", ok: true },
      { type: "done" },
    ]);
  });

  it("propagates ok=false on tool_call_finished", async () => {
    const stream = streamFromChunks([
      `event: tool_call_finished\ndata: {"id":"tc2","ok":false}\n\n`,
    ]);
    const out = await collect(stream);
    expect(out).toEqual([
      { type: "tool_call_finished", id: "tc2", ok: false },
    ]);
  });

  it("yields multiple events from a single chunk containing two blocks", async () => {
    const stream = streamFromChunks([
      `event: text\ndata: {"delta":"A"}\n\nevent: text\ndata: {"delta":"B"}\n\n`,
    ]);
    const out = await collect(stream);
    expect(out).toEqual([
      { type: "text", delta: "A" },
      { type: "text", delta: "B" },
    ]);
  });

  it("reassembles an event split across chunk boundaries", async () => {
    const stream = streamFromChunks([
      `event: text\ndata: {"delta":"`,
      `跨块"}\n\n`,
    ]);
    const out = await collect(stream);
    expect(out).toEqual([{ type: "text", delta: "跨块" }]);
  });

  it("drops a malformed-JSON event but yields subsequent events", async () => {
    const stream = streamFromChunks([
      `event: text\ndata: {"delta":\n\n`,        // broken JSON
      `event: text\ndata: {"delta":"ok"}\n\n`,    // good
    ]);
    const out = await collect(stream);
    expect(out).toEqual([{ type: "text", delta: "ok" }]);
  });

  it("yields error events with message + code", async () => {
    const stream = streamFromChunks([
      `event: error\ndata: {"message":"boom","code":"system"}\n\n`,
    ]);
    const out = await collect(stream);
    expect(out).toEqual([
      { type: "error", message: "boom", code: "system" },
    ]);
  });
});

describe("citations event", () => {
  it("parses citations event", async () => {
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode(
          'event: citations\ndata: {"chunks":[{"doc_id":"d1","filename":"x.pdf","page_no":12,"snippet":"s","score":0.8}]}\n\n'
        ));
        c.enqueue(new TextEncoder().encode('event: done\ndata: {}\n\n'));
        c.close();
      }
    });
    const events: any[] = [];
    for await (const ev of parseSSE(stream)) events.push(ev);
    const cit = events.find(e => e.type === 'citations');
    expect(cit).toBeDefined();
    expect(cit.chunks[0].page_no).toBe(12);
  });

  it("parses empty citations event", async () => {
    const stream = new ReadableStream({
      start(c) {
        c.enqueue(new TextEncoder().encode('event: citations\ndata: {"chunks":[]}\n\n'));
        c.close();
      }
    });
    const events: any[] = [];
    for await (const ev of parseSSE(stream)) events.push(ev);
    expect(events[0].chunks).toEqual([]);
  });
});
