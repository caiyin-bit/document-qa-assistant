import { useCallback, useEffect, useState } from 'react';
import { listDocuments } from './api';
import type { Document } from './types';

export function useDocuments(sessionId: string) {
  const [docs, setDocs] = useState<Document[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDocs(await listDocuments(sessionId));
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, [sessionId]);

  useEffect(() => { refresh(); }, [refresh]);

  // Poll while any doc is processing
  useEffect(() => {
    const anyProcessing = docs.some(d => d.status === 'processing');
    if (!anyProcessing) return;
    const t = setInterval(refresh, 1000);
    return () => clearInterval(t);
  }, [docs, refresh]);

  return { docs, error, refresh, setDocs };
}
