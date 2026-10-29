"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Doc,
  ESTADOS,
  ExportRow,
  downloadFile,
  duracionLegible,
  fetchDoc,
  fetchDocs,
  fetchExports,
} from "@/lib/api";
import { useAudioExport } from "@/components/useAudioExport";

const YT_RE = /^https?:\/\/(www\.|music\.)?(youtube\.com|youtu\.be)\//i;

export default function EditarAudioPage() {
  return (
    <Suspense
      fallback={<p className="py-20 text-center text-slate-400">Cargando estudio…</p>}
    >
      <Estudio />
    </Suspense>
  );
}

function Estudio() {
  const params = useSearchParams();
  const docId = params.get("doc");
  const [doc, setDoc] = useState<Doc | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [url, setUrl] = useState("");
  const [vol, setVol] = useState(15); // dB bajo la voz: -{vol} dB (0–30)
  const [exportsList, setExportsList] = useState<ExportRow[]>([]);
  const [error, setError] = useState("");
  const exporter = useAudioExport();

  const cargarExports = useCallback((id: string) => {
    fetchExports(id).then(setExportsList).catch(() => {});
  }, []);

  useEffect(() => {
    if (docId) {
      fetchDoc(docId)
        .then((d) => {
          setDoc(d);
          cargarExports(d.id);
        })
        .catch((e) => setError((e as Error).message));
    } else {
      fetchDocs()
        .then((ds) => {
          setDocs(ds);
          const listo = ds.find((d) => d.estado === "ready") ?? ds[0];
          if (listo) {
            setDoc(listo);
            cargarExports(listo.id);
          }
        })
        .catch((e) => setError((e as Error).message));
    }
  }, [docId, cargarExports]);

  // Al cerrarse un export (busy true→false) refrescar el historial
  const [prevBusy, setPrevBusy] = useState(false);
  useEffect(() => {
    if (prevBusy && !exporter.busy && doc) cargarExports(doc.id);
    setPrevBusy(exporter.busy);
  }, [exporter.busy, prevBusy, doc, cargarExports]);

  const urlValida = url.trim() === "" || YT_RE.test(url.trim());
  const puedeCrear = Boolean(doc) && url.trim() !== "" && urlValida && !exporter.busy;

  const crear = () => {
    if (!doc || !puedeCrear) return;
    exporter.start(doc, { musicaUrl: url.trim(), volumenDb: -vol });
  };

  const est = doc ? ESTADOS[doc.estado] : null;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Encabezado */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="mb-1 text-xs text-slate-400">
            <Link href="/" className="hover:text-brand-600">
              Biblioteca
            </Link>
            {doc && (
              <>
                {" › "}
                <Link href={`/lector/${doc.id}`} className="hover:text-brand-600">
                  Lector
                </Link>
              </>
            )}
            {" › "}
            <span className="text-slate-500">Editar audio</span>
          </p>
          <h1 className="text-2xl font-bold text-slate-900">Estudio de audio</h1>
          <p className="text-sm text-slate-500">
            Sumá música de fondo al audiolibro y descargalo como un solo MP3.
          </p>
        </div>
        {doc && (
          <Link
            href={`/lector/${doc.id}`}
            className="shrink-0 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-600 shadow-sm hover:bg-slate-50"
          >
            Ir al lector →
          </Link>
        )}
      </div>

      {error && (
        <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          {error}
        </p>
      )}

      {/* 1 · Documento base */}
      <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <h2 className="font-semibold text-slate-900">
          <span className="mr-2 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-bold text-brand-700">
            1
          </span>
          Documento base
        </h2>
        {!docId && docs.length > 0 && (
          <select
            value={doc?.id ?? ""}
            onChange={(e) => {
              const d = docs.find((x) => x.id === e.target.value);
              if (d) {
                setDoc(d);
                setExportsList([]);
                cargarExports(d.id);
              }
            }}
            className="mt-3 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm"
          >
            {docs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.titulo}
              </option>
            ))}
          </select>
        )}
        {doc ? (
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div className="rounded-xl bg-slate-50 p-3">
              <dt className="text-xs text-slate-400">Título</dt>
              <dd className="mt-0.5 line-clamp-2 font-medium text-slate-800">{doc.titulo}</dd>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <dt className="text-xs text-slate-400">Audio base</dt>
              <dd className="mt-0.5 font-medium text-slate-800">
                {duracionLegible(doc.duracion_total_seg)}
              </dd>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <dt className="text-xs text-slate-400">Voz</dt>
              <dd className="mt-0.5 font-medium text-slate-800">{doc.voz_clave ?? "—"}</dd>
            </div>
            <div className="rounded-xl bg-slate-50 p-3">
              <dt className="text-xs text-slate-400">Estado</dt>
              <dd className="mt-0.5">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${est?.cls}`}>
                  {est?.label ?? doc.estado}
                </span>
              </dd>
            </div>
          </dl>
        ) : (
          !error && <p className="mt-3 text-sm text-slate-400">Cargando documento…</p>
        )}
      </section>

      {/* 2 · Música de fondo */}
      <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <h2 className="font-semibold text-slate-900">
          <span className="mr-2 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-bold text-brand-700">
            2
          </span>
          Música de fondo
          <span className="ml-2 text-xs font-normal text-slate-400">YouTube</span>
        </h2>

        <label className="mt-4 block text-sm font-medium text-slate-700" htmlFor="yt-url">
          URL de la canción o playlist
        </label>
        <input
          id="yt-url"
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=… · https://www.youtube.com/playlist?list=…"
          className={`mt-1 w-full rounded-xl border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-200 ${
            urlValida ? "border-slate-200" : "border-rose-300 bg-rose-50"
          }`}
        />
        {!urlValida ? (
          <p className="mt-1 text-xs text-rose-600">
            La URL debe ser de youtube.com, music.youtube.com o youtu.be
          </p>
        ) : (
          <p className="mt-1 text-xs text-slate-400">
            Playlist: se concatenan sus pistas en orden (máx. 30). La música se repite en
            bucle si no cubre la duración y baja sola cuando la voz habla (ducking).
          </p>
        )}

        <div className="mt-5">
          <div className="flex items-baseline justify-between">
            <label htmlFor="vol" className="text-sm font-medium text-slate-700">
              Volumen de la música
            </label>
            <span className="text-sm font-semibold text-brand-700">−{vol} dB</span>
          </div>
          <input
            id="vol"
            type="range"
            min={0}
            max={30}
            step={1}
            value={vol}
            onChange={(e) => setVol(Number(e.target.value))}
            className="mt-1 w-full accent-brand-600"
          />
          <div className="flex justify-between text-[11px] text-slate-400">
            <span>más presente</span>
            <span>−15 dB (equilibrado)</span>
            <span>casi inaudible</span>
          </div>
        </div>

        <button
          onClick={crear}
          disabled={!puedeCrear}
          className="mt-5 w-full rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-brand-100 transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
        >
          {exporter.busy ? "Procesando…" : "🎧 Crear audio con música y descargar"}
        </button>
        <p className="mt-2 text-center text-xs text-slate-400">
          Se descarga la música, se mezcla bajo la voz y el MP3 llega a tu carpeta de
          descargas.
        </p>
      </section>

      {/* 3 · Historial */}
      <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <h2 className="font-semibold text-slate-900">
          <span className="mr-2 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-bold text-brand-700">
            3
          </span>
          Descargas anteriores
        </h2>
        {exportsList.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">
            Todavía no hay exports para este documento.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100">
            {exportsList.map((e) => (
              <li key={e.id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="text-lg">{e.formato === "mp3m" ? "🎵" : "🎧"}</span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-800">
                      {e.formato === "mp3m" ? "MP3 con música de fondo" : "MP3 solo voz"}
                    </p>
                    <p className="text-xs text-slate-400">
                      {e.estado === "done"
                        ? `${duracionLegible(e.duracion_total_seg)} · ${
                            e.created_at
                              ? new Date(e.created_at).toLocaleString("es")
                              : ""
                          }`
                        : e.estado}
                    </p>
                  </div>
                </div>
                {e.download_url && (
                  <button
                    onClick={() => downloadFile(e.download_url!)}
                    className="shrink-0 rounded-lg border border-brand-200 bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-100"
                  >
                    Descargar
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {exporter.node}
    </div>
  );
}
