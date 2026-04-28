import type { SessionSummary, HistoricalMessage, Document } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE!;

export const API_BASE = BASE;
export const STREAM_URL = `${BASE}/chat/stream`;

// All requests need credentials so the session cookie flows.
// We patch fetch implicitly by using these helpers everywhere.
const FETCH_INIT: RequestInit = { credentials: "include" };

export type Me = {
  user_id: string;
  email: string | null;
  name: string;
  is_demo: boolean;
};

export async function getMe(): Promise<Me | null> {
  const r = await fetch(`${BASE}/auth/me`, FETCH_INIT);
  if (r.status === 401) return null;
  if (!r.ok) throw new Error(`GET /auth/me: ${r.status}`);
  return r.json();
}

export async function login(email: string, password: string): Promise<Me> {
  const r = await fetch(`${BASE}/auth/login`, {
    ...FETCH_INIT,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `登录失败: ${r.status}`);
  }
  return r.json();
}

export async function register(
  email: string, password: string, name?: string,
): Promise<Me> {
  const r = await fetch(`${BASE}/auth/register`, {
    ...FETCH_INIT,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name }),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `注册失败: ${r.status}`);
  }
  return r.json();
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, {
    ...FETCH_INIT,
    method: "POST",
  });
}

export async function listSessions(): Promise<SessionSummary[]> {
  const r = await fetch(`${BASE}/sessions?limit=50`, FETCH_INIT);
  if (!r.ok) throw new Error(`GET /sessions: ${r.status}`);
  return r.json();
}

export async function createSession(): Promise<{ session_id: string }> {
  const r = await fetch(`${BASE}/sessions`, { ...FETCH_INIT, method: "POST" });
  if (!r.ok) throw new Error(`POST /sessions: ${r.status}`);
  return r.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const r = await fetch(`${BASE}/sessions/${sessionId}`, { ...FETCH_INIT, method: "DELETE" });
  if (!r.ok) throw new Error(`DELETE /sessions/${sessionId}: ${r.status}`);
}

export async function listMessages(
  sessionId: string,
): Promise<HistoricalMessage[]> {
  const r = await fetch(`${BASE}/sessions/${sessionId}/messages`, FETCH_INIT);
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
  const r = await fetch(`${BASE}/sessions/${sessionId}/documents`, { ...FETCH_INIT,
    method: 'POST', body: fd,
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Upload failed: ${r.status}`);
  }
  return r.json();
}

export async function listDocuments(sessionId: string): Promise<Document[]> {
  const r = await fetch(`${BASE}/sessions/${sessionId}/documents`, FETCH_INIT);
  if (!r.ok) throw new Error(`List failed: ${r.status}`);
  return r.json();
}

export async function deleteDocument(
  sessionId: string, documentId: string
): Promise<void> {
  const r = await fetch(
    `${BASE}/sessions/${sessionId}/documents/${documentId}`,
    { ...FETCH_INIT, method: 'DELETE' }
  );
  if (r.status === 409) throw new Error('正在解析中，请稍后再删除');
  if (!r.ok) throw new Error(`Delete failed: ${r.status}`);
}

export function progressUrl(sessionId: string, documentId: string): string {
  return `${BASE}/sessions/${sessionId}/documents/${documentId}/progress`;
}

export type LibraryDocument = {
  document_id: string;
  filename: string;
  page_count: number;
  uploaded_at: string | null;
};

export async function listUserLibrary(
  sessionId: string,
): Promise<LibraryDocument[]> {
  const r = await fetch(
    `${BASE}/sessions/${sessionId}/documents/library`,
    FETCH_INIT,
  );
  if (!r.ok) throw new Error(`GET library: ${r.status}`);
  return r.json();
}

export async function attachDocuments(
  sessionId: string, documentIds: string[],
): Promise<void> {
  const r = await fetch(
    `${BASE}/sessions/${sessionId}/documents/attach`,
    {
      ...FETCH_INIT,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_ids: documentIds }),
    },
  );
  if (!r.ok) throw new Error(`POST attach: ${r.status}`);
}

export type DocIntro = { summary: string; questions: string[] };

export async function getDocumentIntro(
  sessionId: string, documentId: string,
): Promise<DocIntro> {
  // Cached in localStorage so re-renders / session re-opens don't re-bill.
  // Cache key includes documentId, which is stable per upload (re-upload
  // gets a fresh UUID, naturally invalidating).
  const key = `doc-intro:${documentId}`;
  if (typeof window !== "undefined") {
    const cached = window.localStorage.getItem(key);
    if (cached) {
      try { return JSON.parse(cached); } catch { /* fall through */ }
    }
  }
  const r = await fetch(
    `${BASE}/sessions/${sessionId}/documents/${documentId}/intro`,
    FETCH_INIT,
  );
  if (!r.ok) throw new Error(`GET intro: ${r.status}`);
  const data: DocIntro = await r.json();
  if (typeof window !== "undefined") {
    window.localStorage.setItem(key, JSON.stringify(data));
  }
  return data;
}
