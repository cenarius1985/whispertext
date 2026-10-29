"use client";

import Link from "next/link";
import { Doc, Paragraph } from "@/lib/api";

interface Props {
  doc: Doc;
  current: Paragraph | null;
  currentPos: number;
  total: number;
  playing: boolean;
  waitingId: string | null;
  rate: number;
  autoNext: boolean;
  onRate: (r: number) => void;
  onAutoNext: (v: boolean) => void;
  onToggle: () => void;
  onPrev: () => void;
  onNext: () => void;
  onExport: () => void;
}

const VELOCIDADES = [0.75, 1, 1.25, 1.5, 2];

export default function PlayerPanel(p: Props) {
  const pct = p.total ? Math.round(((p.currentPos + 1) / p.total) * 100) : 0;

  return (
    <aside className="top-20 h-fit space-y-4 lg:sticky">
      <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
          Reproduciendo
        </p>
        <p className="mt-1 line-clamp-3 text-sm font-medium text-slate-800">
          {p.current ? p.current.texto.slice(0, 140) + (p.current.texto.length > 140 ? "…" : "") : "Elige un párrafo para empezar"}
        </p>

        <div className="mt-4 flex items-center justify-center gap-6">
          <button
            onClick={p.onPrev}
            className="rounded-full p-2 text-slate-500 hover:bg-slate-100"
            title="Párrafo anterior (↑)"
          >
            ⏮
          </button>
          <button
            onClick={p.onToggle}
            className="grid h-14 w-14 place-items-center rounded-full bg-brand-600 text-xl text-white shadow-lg shadow-brand-100 hover:bg-brand-700"
            title="Play/Pausa (espacio)"
          >
            {p.playing ? "⏸" : "▶"}
          </button>
          <button
            onClick={p.onNext}
            className="rounded-full p-2 text-slate-500 hover:bg-slate-100"
            title="Párrafo siguiente (↓)"
          >
            ⏭
          </button>
        </div>

        {p.waitingId && (
          <p className="mt-3 flex items-center justify-center gap-2 text-xs text-brand-600">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-brand-100 border-t-brand-600" />
            sintetizando este párrafo…
          </p>
        )}

        <div className="mt-4">
          <div className="mb-1 flex justify-between text-xs text-slate-400">
            <span>
              {p.currentPos >= 0 ? `párrafo ${p.currentPos + 1} de ${p.total}` : `${p.total} párrafos`}
            </span>
            <span>{pct}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>
      </div>

      <div className="space-y-3 rounded-2xl bg-white p-5 text-sm shadow-sm ring-1 ring-slate-200">
        <label className="flex items-center justify-between">
          <span className="text-slate-500">Velocidad</span>
          <select
            value={p.rate}
            onChange={(e) => p.onRate(Number(e.target.value))}
            className="rounded-lg border border-slate-200 px-2 py-1"
          >
            {VELOCIDADES.map((v) => (
              <option key={v} value={v}>
                {v}×
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center justify-between">
          <span className="text-slate-500">Auto-avance</span>
          <input
            type="checkbox"
            checked={p.autoNext}
            onChange={(e) => p.onAutoNext(e.target.checked)}
            className="h-4 w-8 accent-brand-600"
          />
        </label>
        <p className="text-xs text-slate-400">
          Voz: {p.doc.voz_clave} · idioma {p.doc.idioma_lectura} · v{p.doc.version_actual}
        </p>
        <button
          onClick={p.onExport}
          disabled={p.doc.estado !== "ready"}
          className="w-full rounded-xl border border-brand-200 bg-brand-50 px-3 py-2 font-medium text-brand-700 hover:bg-brand-100 disabled:opacity-40"
        >
          Exportar audio completo
        </button>
        <Link
          href={`/editar-audio?doc=${p.doc.id}`}
          className="block text-center text-xs text-slate-500 underline-offset-2 hover:text-brand-600 hover:underline"
        >
          Editar audio · música de fondo
        </Link>
        <p className="text-[11px] leading-4 text-slate-400">
          Atajos: espacio play/pausa · ↑/↓ párrafo. El párrafo en reproducción queda
          resaltado a la izquierda.
        </p>
      </div>
    </aside>
  );
}
