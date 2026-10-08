"use client";

import { useEffect, useState } from "react";
import { Voice, fetchVoices } from "@/lib/api";

export default function AjustesPage() {
  const [voces, setVoces] = useState<Voice[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchVoices().then(setVoces).catch((e) => setError((e as Error).message));
  }, []);

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Ajustes</h1>
        <p className="text-sm text-slate-500">
          Configuración del stack (los valores viven en <code>.env</code> del backend).
        </p>
      </div>

      <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <h2 className="font-semibold text-slate-900">Voces Piper disponibles</h2>
        {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}
        <ul className="mt-3 space-y-2">
          {voces.map((v) => (
            <li
              key={v.id}
              className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-2 text-sm"
            >
              <span>
                {v.nombre} <span className="text-slate-400">({v.idioma} · {v.calidad})</span>
              </span>
              {v.es_default && (
                <span className="rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700">
                  por defecto
                </span>
              )}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-slate-400">
          La voz por defecto se define con <code>PIPER_VOICE_DEFAULT</code>{" "}
          (actual: <code>es_AR-daniela-high</code>).
        </p>
      </section>

      <section className="rounded-2xl bg-white p-5 text-sm shadow-sm ring-1 ring-slate-200">
        <h2 className="font-semibold text-slate-900">Motor e integraciones</h2>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-slate-600">
          <li>TTS: Piper local (CPU) — audios MP3 cacheados por hash de párrafo.</li>
          <li>
            Bonsai (LLM local, opcional): clasificación editorial y traducción de
            apoyo. Si está apagado, todo sigue funcionando en modo determinista.
          </li>
          <li>OCR: Tesseract (spa+eng) para páginas escaneadas.</li>
          <li>Traducción local: Argos Translate (instalación opcional).</li>
        </ul>
      </section>
    </div>
  );
}
