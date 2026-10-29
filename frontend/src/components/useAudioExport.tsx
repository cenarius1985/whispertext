"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Doc,
  ExportRow,
  downloadFile,
  duracionLegible,
  fetchExports,
  fetchJob,
  startExport,
} from "@/lib/api";

type Fase = "idle" | "consolidando" | "listo" | "error";

const POLL_MS = 1500;
const TIMEOUT_MS = 15 * 60_000;

const TEXTO_ETAPA: Record<string, string> = {
  preparando_voz: "Preparando la voz del documento…",
  descargando_musica: "Descargando música de YouTube…",
  mezclando: "Mezclando música y voz con ducking…",
};

/**
 * Export con diálogo y descarga automática: lanza el job, muestra el estado
 * (por etapas si trae música) y al terminar dispara la descarga en el
 * navegador (el backend sirve el MP3 con Content-Disposition: attachment).
 */
export function useAudioExport() {
  const [fase, setFase] = useState<Fase>("idle");
  const [titulo, setTitulo] = useState("");
  const [etapa, setEtapa] = useState("");
  const [conMusica, setConMusica] = useState(false);
  const [error, setError] = useState("");
  const [exportRow, setExportRow] = useState<ExportRow | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const detener = useCallback(() => {
    if (timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => detener, [detener]);

  const cerrar = useCallback(() => {
    detener();
    setFase("idle");
  }, [detener]);

  const start = useCallback(
    async (doc: Doc, opts?: { musicaUrl?: string; volumenDb?: number }) => {
      detener();
      setTitulo(doc.titulo);
      setError("");
      setExportRow(null);
      setEtapa("");
      setConMusica(Boolean(opts?.musicaUrl));
      setFase("consolidando");
      try {
        const { jobId, exportId } = await startExport(doc.id, opts);
        await new Promise<void>((resolve, reject) => {
          const t0 = Date.now();
          timer.current = setInterval(async () => {
            try {
              const job = await fetchJob(jobId);
              setEtapa(String(job.detalle?.etapa ?? ""));
              if (job.estado === "done") {
                detener();
                resolve();
              } else if (job.estado === "error") {
                detener();
                reject(new Error(job.error || "el export falló"));
              } else if (Date.now() - t0 > TIMEOUT_MS) {
                detener();
                reject(
                  new Error("el export está tardando demasiado; inténtalo de nuevo más tarde")
                );
              }
            } catch {
              /* error de red transitorio: seguir intentando hasta el timeout */
            }
          }, POLL_MS);
        });
        const rows = await fetchExports(doc.id);
        const row = rows.find((r) => r.id === exportId) ?? rows.find((r) => r.download_url);
        if (!row?.download_url) throw new Error("el export terminó pero no hay archivo");
        setExportRow(row);
        setFase("listo");
        downloadFile(row.download_url);
      } catch (e) {
        setError((e as Error).message);
        setFase("error");
      }
    },
    [detener]
  );

  const textoTrabajo = conMusica
    ? TEXTO_ETAPA[etapa] ?? "Preparando audio con música…"
    : "Consolidando audio…";

  const node =
    fase === "idle" ? null : (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
        <div className="w-full max-w-sm rounded-2xl bg-white p-6 text-center shadow-xl ring-1 ring-slate-200">
          {fase === "consolidando" && (
            <>
              <span className="mx-auto block h-10 w-10 animate-spin rounded-full border-4 border-brand-100 border-t-brand-600" />
              <h3 className="mt-4 font-semibold text-slate-900">{textoTrabajo}</h3>
              <p className="mt-1 line-clamp-2 text-sm text-slate-500">«{titulo}»</p>
              <p className="mt-3 text-xs text-slate-400">
                La descarga comenzará en breve. Podés seguir usando la app.
              </p>
            </>
          )}
          {fase === "listo" && (
            <>
              <span className="text-3xl">🎧</span>
              <h3 className="mt-2 font-semibold text-slate-900">
                {conMusica ? "¡Audio con música listo!" : "¡Audio listo!"}
              </h3>
              <p className="mt-1 text-sm text-slate-500">
                {exportRow ? duracionLegible(exportRow.duracion_total_seg) : ""} de audio · MP3
              </p>
              <p className="mt-2 text-xs text-slate-400">
                La descarga debería haber comenzado. Si no fue así:
              </p>
              <button
                onClick={() => exportRow?.download_url && downloadFile(exportRow.download_url)}
                className="mt-3 w-full rounded-xl bg-brand-600 px-3 py-2 font-medium text-white hover:bg-brand-700"
              >
                Descargar MP3
              </button>
            </>
          )}
          {fase === "error" && (
            <>
              <span className="text-3xl">⚠️</span>
              <h3 className="mt-2 font-semibold text-rose-600">No se pudo exportar</h3>
              <p className="mt-2 break-words text-sm text-slate-500">{error}</p>
            </>
          )}
          <button
            onClick={cerrar}
            className="mt-4 rounded-lg px-4 py-1.5 text-sm text-slate-500 hover:bg-slate-100"
          >
            Cerrar
          </button>
        </div>
      </div>
    );

  return { start, node, busy: fase === "consolidando" };
}
