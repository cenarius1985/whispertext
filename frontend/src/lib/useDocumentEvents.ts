"use client";

import { useEffect, useRef } from "react";
import { API_URL } from "@/lib/api";

/** SSE por documento: dispara onEvent con cada payload del worker. */
export function useDocumentEvents(
  documentId: string | null,
  onEvent: (data: Record<string, unknown>) => void
) {
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = documentId
      ? `${API_URL}/api/events?document_id=${documentId}`
      : `${API_URL}/api/events`;
    const es = new EventSource(url);
    es.onmessage = (ev) => {
      try {
        cbRef.current(JSON.parse(ev.data));
      } catch {}
    };
    es.onerror = () => es.close(); // reconecta remontando el componente
    return () => es.close();
  }, [documentId]);
}
