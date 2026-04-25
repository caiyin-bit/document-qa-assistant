import type { SessionSummary, HistoricalMessage, Document } from "./types";

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

export async function deleteSession(sessionId: string): Promise<void> {
  const r = await fetch(`${BASE}/sessions/${sessionId}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`DELETE /sessions/${sessionId}: ${r.status}`);
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

export async function uploadDocument(
  sessionId: string, file: File
): Promise<Document> {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(`${BASE}/sessions/${sessionId}/documents`, {
    method: 'POST', body: fd,
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Upload failed: ${r.status}`);
  }
  return r.json();
}

export async function listDocuments(sessionId: string): Promise<Document[]> {
  const r = await fetch(`${BASE}/sessions/${sessionId}/documents`);
  if (!r.ok) throw new Error(`List failed: ${r.status}`);
  return r.json();
}

export async function deleteDocument(
  sessionId: string, documentId: string
): Promise<void> {
  const r = await fetch(
    `${BASE}/sessions/${sessionId}/documents/${documentId}`,
    { method: 'DELETE' }
  );
  if (r.status === 409) throw new Error('正在解析中，请稍后再删除');
  if (!r.ok) throw new Error(`Delete failed: ${r.status}`);
}

export function progressUrl(sessionId: string, documentId: string): string {
  return `${BASE}/sessions/${sessionId}/documents/${documentId}/progress`;
}
