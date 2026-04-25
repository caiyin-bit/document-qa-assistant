import type { SessionSummary, HistoricalMessage } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE!;

export const STREAM_URL = `${BASE}/chat/stream`;

export async function listSessions(): Promise<SessionSummary[]> {
  const r = await fetch(`${BASE}/sessions?limit=50`);
  if (!r.ok) throw new Error(`GET /sessions: ${r.status}`);
  return r.json();
}

export async function createSession(): Promise<{ session_id: string }> {
  const r = await fetch(`${BASE}/sessions`, { method: "POST" });
  if (!r.ok) throw new Error(`POST /sessions: ${r.status}`);
  return r.json();
}

export async function listMessages(
  sessionId: string,
): Promise<HistoricalMessage[]> {
  const r = await fetch(`${BASE}/sessions/${sessionId}/messages`);
  if (!r.ok) {
    throw new Error(`GET /sessions/${sessionId}/messages: ${r.status}`);
  }
  return r.json();
}
