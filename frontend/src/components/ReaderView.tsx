"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Doc,
  Paragraph,
  fetchDoc,
  fetchJob,
  fetchParagraphs,
  mediaUrl,
  saveProgress,
  startRenderMd,
  synthesizeParagraph,
} from "@/lib/api";
import { useDocumentEvents } from "@/lib/useDocumentEvents";
import MarkdownText from "@/components/MarkdownText";
import PlayerPanel from "@/components/PlayerPanel";
import { useAudioExport } from "@/components/useAudioExport";

export default function ReaderView({ docId }: { docId: string }) {
  const [doc, setDoc] = useState<Doc | null>(null);
  const [paragraphs, setParagraphs] = useState<Paragraph[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [autoNext, setAutoNext] = useState(true);
  const [waiting, setWaiting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const exporter = useAudioExport();
  const [renderJob, setRenderJob] = useState<{
    estado: string;
    hecho: number;
    total: number;
  } | null>(null);
  const renderTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(
    () => () => {
      if (renderTimer.current) clearInterval(renderTimer.current);
    },
    []
  );

  /** Re-render visual con IA (docs/12): lanza el job y recarga al terminar. */
  const mejorarVisual = async () => {
    if (renderJob) return;
    try {
      const jobId = await startRenderMd(docId);
      setRenderJob({ estado: "running", hecho: 0, total: 0 });
      renderTimer.current = setInterval(async () => {
        try {
          const job = await fetchJob(jobId);
          setRenderJob({ estado: job.estado, hecho: job.hecho, total: job.total });
          if (job.estado === "done") {
            clearInterval(renderTimer.current!);
            renderTimer.current = null;
            setRenderJob(null);
            await cargar();
          } else if (job.estado === "error") {
            clearInterval(renderTimer.current!);
            renderTimer.current = null;
            setRenderJob(null);
            window.alert(job.error || "el re-render falló");
          }
        } catch {
          /* error de red transitorio: el próximo tick reintenta */
        }
      }, 2000);
    } catch (e) {
      window.alert((e as Error).message);
    }
  };

  const cargar = useCallback(async () => {
    try {
      const [d, ps] = await Promise.all([fetchDoc(docId), fetchParagraphs(docId)]);
      setDoc(d);
      setParagraphs(ps);
      return { d, ps };
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [docId]);

  useEffect(() => {
    cargar();
  }, [cargar]);

  // Retomar donde quedó (RF-08): marca el último párrafo escuchado
  useEffect(() => {
    if (!doc || currentId || !paragraphs.length) return;
    if (doc.progreso_indice != null) {
      const target = paragraphs.find((p) => p.indice === doc.progreso_indice);
      if (target) setCurrentId(target.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, paragraphs]);

  const hablables = useMemo(
    () => paragraphs.filter((p) => p.estado_audio !== "skipped"),
    [paragraphs]
  );
  const current = hablables.find((p) => p.id === currentId) ?? null;
  const currentPos = current ? hablables.findIndex((p) => p.id === current.id) : -1;

  const reproducir = useCallback(
    async (p: Paragraph) => {
      setCurrentId(p.id);
      if (p.estado_audio === "ready" && p.audio_url) {
        setWaiting(null);
        const a = audioRef.current;
        if (a) {
          a.src = mediaUrl(p.audio_url);
          a.playbackRate = rate;
          a.play().catch(() => setPlaying(false));
        }
      } else if (p.estado_audio === "pending") {
        setWaiting(p.id);
        try {
          await synthesizeParagraph(p.id); // on-demand: el worker lo prioriza
        } catch {
          setWaiting(null);
        }
      }
    },
    [rate]
  );

  const saltar = useCallback(
    (delta: number) => {
      if (!hablables.length) return;
      const base = currentPos >= 0 ? currentPos : 0;
      const next = base + delta;
      // Sin párrafo previo/siguiente: no hacer nada. Antes se recortaba al
      // extremo y el auto-avance al terminar el último lo reproducía en bucle.
      if (next < 0 || next >= hablables.length) return;
      reproducir(hablables[next]);
    },
    [hablables, currentPos, reproducir]
  );

  // Refresco en vivo: párrafo listo → autoplay si era el que esperábamos
  useDocumentEvents(docId, (ev) => {
    if (ev.type === "paragraph_ready") {
      cargar().then((res) => {
        if (!res) return;
        const listo = res.ps.find((x) => x.id === ev.paragraph_id);
        if (listo?.estado_audio === "ready" && waiting === ev.paragraph_id) {
          setWaiting(null);
          reproducir(listo);
        }
      });
    } else if (ev.type === "job" && ev.estado === "done") {
      cargar();
    }
  });

  // Auto-scroll suave + guardado de progreso
  useEffect(() => {
    if (!currentId) return;
    rowRefs.current.get(currentId)?.scrollIntoView({ behavior: "smooth", block: "center" });
    saveProgress(docId, currentId).catch(() => {});
  }, [currentId, docId]);

  // Atajos de teclado (M-10): espacio, ↑/↓
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
      } else if (e.code === "ArrowDown") saltar(1);
      else if (e.code === "ArrowUp") saltar(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saltar, current]);

  const togglePlay = () => {
    const a = audioRef.current;
    if (!a || !current) return;
    if (playing) {
      a.pause();
      setPlaying(false);
    } else if (current.audio_url) {
      a.play().catch(() => {});
    } else {
      reproducir(current);
    }
  };

  if (error) {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-rose-700">{error}</div>
    );
  }
  if (!doc) return <p className="py-20 text-center text-slate-400">Cargando documento…</p>;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      {/* Columna izquierda: texto con párrafos clicables */}
      <div className="min-h-[70vh]">
        {(() => {
          const cat =
            doc.categorias.find((c) => !c.es_sistema) ?? doc.categorias[0];
          return (
            <div className="mb-4 flex items-baseline justify-between gap-4">
              <div className="min-w-0">
                <p className="mb-1 truncate text-xs text-slate-400">
                  <Link href="/" className="hover:text-brand-600">
                    Biblioteca
                  </Link>
                  {cat && (
                    <>
                      {" › "}
                      <Link
                        href={`/?cat=${cat.id}`}
                        className="hover:text-brand-600"
                      >
                        {cat.icono} {cat.nombre}
                      </Link>
                    </>
                  )}
                </p>
                <h1 className="text-xl font-bold text-slate-900">{doc.titulo}</h1>
              </div>
            </div>
          );
        })()}

        {renderJob && (
          <div className="mb-3 flex items-center gap-2 rounded-xl border border-brand-200 bg-brand-50 px-3 py-2 text-sm text-brand-700">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
            Mejorando la visualización con IA
            {renderJob.total > 0 && (
              <span className="text-xs text-brand-500">
                · lote {renderJob.hecho}/{renderJob.total}
              </span>
            )}
          </div>
        )}

        <div className="space-y-1">
          {paragraphs.map((p) => {
            const esActual = p.id === currentId;
            const esSkipped = p.estado_audio === "skipped";
            // docs/12: bloque absorbido por otro (tabla juntada, nº de
            // ecuación huérfano) — sin imagen no hay nada que mostrar
            if (p.texto_md === "" && !p.imagen_url) return null;
            const esVisual =
              (p.tipo === "figura" || p.tipo === "ecuacion") && p.imagen_url;
            return (
              <div
                key={p.id}
                ref={(el) => {
                  if (el) rowRefs.current.set(p.id, el);
                  else rowRefs.current.delete(p.id);
                }}
                onClick={() => !esSkipped && reproducir(p)}
                className={[
                  "group flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2 transition",
                  esActual ? "parrafo-activo" : "hover:bg-white",
                  esSkipped ? "opacity-40" : "",
                ].join(" ")}
              >
                {esVisual ? (
                  <figure className="mx-auto w-full max-w-xl text-center">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={mediaUrl(p.imagen_url)}
                      alt={p.texto || (p.tipo === "figura" ? "figura" : "ecuación")}
                      className="mx-auto max-h-96 rounded-lg ring-1 ring-slate-200"
                    />
                    <MarkdownText
                      md={p.texto_md}
                      fallback={p.texto}
                      className="mt-1 text-xs leading-5 text-slate-500"
                    />
                  </figure>
                ) : (
                  <MarkdownText
                    md={p.texto_md ?? (p.latex ? `$$${p.latex}$$` : null)}
                    fallback={
                      p.texto || (
                        <em className="text-xs text-slate-400">
                          {p.tipo === "figura" || p.tipo === "ecuacion"
                            ? "sin descripción"
                            : "—"}
                        </em>
                      )
                    }
                    className={[
                      "flex-1 text-[15px]",
                      p.tipo === "titulo"
                        ? "font-semibold text-slate-900"
                        : "text-slate-700",
                    ].join(" ")}
                  />
                )}
                {esSkipped && (
                  <span className="mt-1 shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
                    saltado · {p.skip_reason}
                  </span>
                )}
                {/* Audio por párrafo, a la derecha (RF-06) */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (!esSkipped) reproducir(p);
                  }}
                  disabled={esSkipped}
                  title={`Párrafo ${p.indice + 1}${p.pagina ? ` · pág. ${p.pagina}` : ""}`}
                  className="mt-1 shrink-0 rounded-full p-1.5 text-slate-300 transition hover:bg-brand-50 hover:text-brand-600 disabled:invisible"
                >
                  {waiting === p.id ? (
                    <span className="block h-4 w-4 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
                  ) : p.estado_audio === "error" ? (
                    <span className="text-rose-400">⚠</span>
                  ) : esActual && playing ? (
                    <span className="text-brand-600">⏸</span>
                  ) : (
                    <span>▶</span>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Columna derecha: reproductor fijo */}
      <PlayerPanel
        doc={doc}
        current={current}
        currentPos={currentPos}
        total={hablables.length}
        playing={playing}
        waitingId={waiting}
        rate={rate}
        autoNext={autoNext}
        onRate={(r) => {
          setRate(r);
          if (audioRef.current) audioRef.current.playbackRate = r;
        }}
        onAutoNext={setAutoNext}
        onToggle={togglePlay}
        onPrev={() => saltar(-1)}
        onNext={() => saltar(1)}
        onExport={() => doc && exporter.start(doc)}
        onMejorarVisual={mejorarVisual}
        mejorando={!!renderJob}
      />

      <audio
        ref={audioRef}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          if (autoNext) saltar(1);
        }}
        hidden
      />
      {exporter.node}
    </div>
  );
}
