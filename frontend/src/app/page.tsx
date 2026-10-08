"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Doc, fetchDocs, uploadDocument } from "@/lib/api";
import { useDocumentEvents } from "@/lib/useDocumentEvents";
import DocumentCard from "@/components/DocumentCard";

export default function BibliotecaPage() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [q, setQ] = useState("");
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const recargar = useCallback(async (query?: string) => {
    try {
      setDocs(await fetchDocs(query ?? q));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [q]);

  useEffect(() => {
    const t = setTimeout(() => recargar(), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  // Refresco en vivo mientras el worker procesa
  useDocumentEvents(null, (ev) => {
    if (ev.type === "job" || ev.type === "paragraph_ready") recargar();
  });

  const subir = async (files: FileList | null) => {
    if (!files?.length) return;
    setSubiendo(true);
    setError(null);
    try {
      for (const f of Array.from(files)) {
        try {
          await uploadDocument(f);
        } catch (e) {
          const msg = (e as Error).message;
          setError(
            msg.includes("ya existe")
              ? `“${f.name}” ya estaba en la biblioteca (nada reprocesado).`
              : `${f.name}: ${msg}`
          );
        }
      }
      await recargar();
    } finally {
      setSubiendo(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const procesando = docs.some((d) =>
    ["pending", "extracting", "cleaning", "synthesizing"].includes(d.estado)
  );

  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Biblioteca</h1>
          <p className="text-sm text-slate-500">
            {docs.length} documento{docs.length === 1 ? "" : "s"}
            {procesando && " · procesando… (se actualiza en vivo)"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar por título o contenido…"
            className="w-64 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
          />
          <button
            onClick={() => inputRef.current?.click()}
            disabled={subiendo}
            className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow hover:bg-brand-700 disabled:opacity-50"
          >
            {subiendo ? "Subiendo…" : "+ Subir PDF"}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            multiple
            hidden
            onChange={(e) => subir(e.target.files)}
          />
        </div>
      </section>

      {error && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {error}
        </div>
      )}

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          subir(e.dataTransfer.files);
        }}
        className="rounded-2xl border-2 border-dashed border-slate-200 p-4 text-center text-sm text-slate-400"
      >
        Arrastra PDFs aquí para agregarlos a la biblioteca
      </div>

      {docs.length === 0 ? (
        <p className="py-16 text-center text-slate-400">
          Aún no hay documentos. Sube el primero con “+ Subir PDF”.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {docs.map((d) => (
            <DocumentCard key={d.id} doc={d} onChanged={() => recargar()} />
          ))}
        </div>
      )}
    </div>
  );
}
