"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import {
  ACCEPT_UPLOAD,
  Doc,
  ESTADOS,
  FORMATOS,
  Voice,
  deleteDocument,
  fetchVoices,
  mediaUrl,
  renameDocument,
  reprocessDocument,
  replaceDocument,
  setDocCategories,
  uploadCover,
} from "@/lib/api";
import { useAudioExport } from "@/components/useAudioExport";

export default function DocumentCard({
  doc,
  onChanged,
  onOrganize,
  onFilterCat,
  favId,
}: {
  doc: Doc;
  onChanged: () => void;
  onOrganize: () => void;
  onFilterCat: (cid: string) => void;
  favId: string | null;
}) {
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState(false);
  const replaceRef = useRef<HTMLInputElement>(null);
  const coverRef = useRef<HTMLInputElement>(null);
  const exporter = useAudioExport();
  const est = ESTADOS[doc.estado] ?? { label: doc.estado, cls: "bg-slate-100 text-slate-600" };
  const fmt = FORMATOS[doc.formato] ?? FORMATOS.pdf;
  const progreso =
    doc.progreso_indice != null && doc.total_parrafos_activos > 0
      ? Math.round(((doc.progreso_indice + 1) / doc.total_parrafos_activos) * 100)
      : 0;
  const esFav = favId != null && doc.categorias.some((c) => c.id === favId);

  const toggleFav = async () => {
    if (favId == null) return;
    setBusy(true);
    try {
      const ids = doc.categorias.map((c) => c.id).filter((id) => id !== favId);
      if (!esFav) ids.push(favId);
      await setDocCategories(doc.id, ids);
      onChanged();
    } catch (e) {
      window.alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cambiarVoz = async () => {
    setBusy(true);
    try {
      const voces: Voice[] = await fetchVoices();
      const actual = voces.find((v) => v.clave === doc.voz_clave);
      const otras = voces.filter((v) => v.clave !== actual?.clave);
      const opts = otras.map((v) => `${v.nombre} (${v.idioma})`).join(" | ");
      const elegida = window.prompt(
        `Cambiar voz (actual: ${actual?.nombre ?? doc.voz_clave}).\nOpciones: ${opts}\n\nEscribe el número (1-${otras.length}):`,
        "1"
      );
      const n = parseInt(elegida ?? "", 10);
      if (n >= 1 && n <= otras.length) {
        await reprocessDocument(doc.id, { voz_clave: otras[n - 1].clave });
        onChanged();
      }
    } finally {
    }
    setBusy(false);
  };

  const acciones = async (fn: () => Promise<void>, confirmar?: string) => {
    if (confirmar && !window.confirm(confirmar)) return;
    setBusy(true);
    try {
      await fn();
      onChanged();
    } catch (e) {
      window.alert((e as Error).message);
    } finally {
      setBusy(false);
      setMenu(false);
    }
  };

  return (
    <article className="group relative flex flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-slate-200 transition hover:shadow-md">
      <Link href={`/lector/${doc.id}`} className="block">
        <div className="relative aspect-[3/4] w-full overflow-hidden bg-gradient-to-br from-brand-600 to-indigo-900">
          {doc.portada_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaUrl(doc.portada_url)}
              alt={doc.titulo}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center p-4 text-center">
              <span className="line-clamp-4 text-lg font-semibold text-white drop-shadow">
                {doc.titulo}
              </span>
            </div>
          )}
          <span
            className={`absolute left-3 top-3 rounded-full px-2.5 py-1 text-xs font-medium ${est.cls}`}
          >
            {est.label}
          </span>
          <span
            className={`absolute right-3 top-3 rounded-full px-2 py-1 text-[10px] font-bold tracking-wide ${fmt.cls}`}
          >
            {fmt.label}
          </span>
          {favId != null && (
            <button
              disabled={busy}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                toggleFav();
              }}
              className={`absolute bottom-3 right-3 grid h-8 w-8 place-items-center rounded-full text-lg backdrop-blur transition ${
                esFav ? "bg-amber-400/90 text-white" : "bg-black/30 text-white/70 opacity-0 group-hover:opacity-100"
              }`}
              title={esFav ? "Quitar de Favoritos" : "Agregar a Favoritos"}
            >
              ★
            </button>
          )}
        </div>
      </Link>

      <div className="flex flex-1 flex-col gap-2 p-4">
        <Link href={`/lector/${doc.id}`} className="line-clamp-2 font-semibold text-slate-900 hover:text-brand-600">
          {doc.titulo}
        </Link>
        {doc.categorias.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {doc.categorias.map((c) => (
              <button
                key={c.id}
                onClick={() => onFilterCat(c.id)}
                className="rounded-full px-2 py-0.5 text-xs hover:opacity-80"
                style={{ backgroundColor: `${c.color}1a`, color: c.color }}
                title={`Filtrar por ${c.nombre}`}
              >
                {c.icono} {c.nombre}
              </button>
            ))}
          </div>
        )}
        <p className="text-xs text-slate-400">
          v{doc.version_actual} · {doc.voz_clave ?? "—"} · {doc.idioma_lectura}
        </p>
        <div className="mt-auto">
          <div className="mb-1 flex justify-between text-xs text-slate-400">
            <span>leído</span>
            <span>{progreso}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-brand-500" style={{ width: `${progreso}%` }} />
          </div>
        </div>

        <div className="mt-2 flex items-center gap-2">
          <Link
            href={`/lector/${doc.id}`}
            className="flex-1 rounded-lg bg-brand-600 px-3 py-1.5 text-center text-sm font-medium text-white hover:bg-brand-700"
          >
            Leer
          </Link>
          <button
            disabled={busy}
            onClick={onOrganize}
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm text-slate-500 hover:bg-slate-50"
            title="Organizar en categorías"
          >
            🏷
          </button>
          <button
            disabled={busy}
            onClick={() => setMenu((m) => !m)}
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm text-slate-500 hover:bg-slate-50"
            title="Más acciones"
          >
            ⋯
          </button>
        </div>

        {menu && (
          <div className="absolute right-3 top-12 z-10 w-52 overflow-hidden rounded-xl bg-white py-1 text-sm shadow-lg ring-1 ring-slate-200">
            <button
              disabled={busy}
              onClick={() => replaceRef.current?.click()}
              className="block w-full px-4 py-2 text-left hover:bg-slate-50"
            >
              Reemplazar archivo (diff)
            </button>
            <button
              disabled={busy}
              onClick={() => acciones(() => cambiarVoz().then(() => {}))}
              className="block w-full px-4 py-2 text-left hover:bg-slate-50"
            >
              Cambiar voz / reprocesar
            </button>
            <button
              disabled={busy}
              onClick={() => {
                setMenu(false);
                exporter.start(doc);
              }}
              className="block w-full px-4 py-2 text-left hover:bg-slate-50"
            >
              Exportar audio completo
            </button>
            <button
              disabled={busy}
              onClick={() => {
                const nuevo = window.prompt("Editar título:", doc.titulo);
                if (nuevo && nuevo.trim() && nuevo.trim() !== doc.titulo) {
                  acciones(() => renameDocument(doc.id, nuevo.trim()));
                }
              }}
              className="block w-full px-4 py-2 text-left hover:bg-slate-50"
            >
              Editar título…
            </button>
            <button
              disabled={busy}
              onClick={() => coverRef.current?.click()}
              className="block w-full px-4 py-2 text-left hover:bg-slate-50"
            >
              Poner portada…
            </button>
            <button
              disabled={busy}
              onClick={() =>
                acciones(
                  () => deleteDocument(doc.id),
                  `¿Eliminar “${doc.titulo}” y todos sus audios?`
                )
              }
              className="block w-full px-4 py-2 text-left text-rose-600 hover:bg-rose-50"
            >
              Eliminar
            </button>
          </div>
        )}
      </div>

      <input
        ref={replaceRef}
        type="file"
        accept={ACCEPT_UPLOAD}
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) acciones(() => replaceDocument(doc.id, f));
          e.target.value = "";
        }}
      />
      <input
        ref={coverRef}
        type="file"
        accept=".png,.jpg,.jpeg,.webp"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) acciones(() => uploadCover(doc.id, f));
          e.target.value = "";
        }}
      />
      {exporter.node}
    </article>
  );
}
