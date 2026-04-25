import { useEffect, useState } from 'react';
import { progressUrl } from './api';

export type Progress =
  | { page: number; total: number; phase: string }
  | { status: 'ready' | 'failed'; error?: string | null };

export function useDocumentProgress(
  sessionId: string, documentId: string, enabled: boolean,
): Progress | null {
  const [progress, setProgress] = useState<Progress | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource(progressUrl(sessionId, documentId));
    es.addEventListener('progress', (e: MessageEvent) => {
      setProgress(JSON.parse(e.data));
    });
    es.addEventListener('done', (e: MessageEvent) => {
      setProgress(JSON.parse(e.data));
      es.close();
    });
    es.onerror = () => es.close();
    return () => es.close();
  }, [sessionId, documentId, enabled]);
  return progress;
}
