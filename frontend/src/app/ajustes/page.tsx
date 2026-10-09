"use client";

import { useCallback, useEffect, useState } from "react";
import {
  LLMVerifyResult,
  Voice,
  fetchLLMConfig,
  fetchLLMModels,
  fetchVoices,
  resetLLMConfig,
  saveLLMConfig,
  verifyLLM,
} from "@/lib/api";

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
          Configuración del stack. El LLM se cambia en caliente (sin reinicio);
          el resto vive en <code>.env</code> del backend.
        </p>
      </div>

      <LLMSection />

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
            LLM (opcional, configurable arriba): ecuaciones, clasificación
            editorial y traducción de apoyo. Si está apagado o caído, todo
            sigue funcionando en modo determinista.
          </li>
          <li>OCR: Tesseract (spa+eng) para páginas escaneadas.</li>
          <li>Traducción local: Argos Translate (instalación opcional).</li>
        </ul>
      </section>
    </div>
  );
}

/* ── Modelo LLM en caliente ──────────────────────────────────────────────── */

function LLMSection() {
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [source, setSource] = useState<string>("");
  const [envDefault, setEnvDefault] = useState<{ base_url: string; model: string } | null>(null);
  const [modelos, setModelos] = useState<string[]>([]);
  const [prueba, setPrueba] = useState<LLMVerifyResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      const cfg = await fetchLLMConfig();
      setBaseUrl(cfg.base_url);
      setModel(cfg.model);
      setEnabled(cfg.enabled);
      setSource(cfg.source);
      setEnvDefault(cfg.env_default);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const cargarCatalogo = async () => {
    setBusy("catalogo");
    setErr(null);
    try {
      setModelos(await fetchLLMModels(baseUrl.trim()));
    } catch (e) {
      setErr(`Catálogo: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const guardar = async () => {
    setBusy("guardar");
    setErr(null);
    setMsg(null);
    try {
      const cfg = await saveLLMConfig({
        base_url: baseUrl.trim(),
        model: model.trim(),
        enabled,
      });
      setSource(cfg.source);
      setMsg(
        `Guardado — api y worker ya lo usan (fuente: ${cfg.source === "archivo" ? "Ajustes" : ".env"}).`
      );
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const probar = async () => {
    setBusy("probar");
    setErr(null);
    setMsg(null);
    try {
      setPrueba(await verifyLLM({ base_url: baseUrl.trim(), model: model.trim() }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const restablecer = async () => {
    setBusy("reset");
    setErr(null);
    setMsg(null);
    try {
      const cfg = await resetLLMConfig();
      setBaseUrl(cfg.base_url);
      setModel(cfg.model);
      setEnabled(cfg.enabled);
      setSource(cfg.source);
      setModelos([]);
      setMsg(`Restablecido al .env (${cfg.base_url} · ${cfg.model}).`);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <div className="flex items-baseline justify-between">
        <h2 className="font-semibold text-slate-900">Modelo LLM (ecuaciones y limpieza)</h2>
        {source && (
          <span
            className={`rounded-full px-2 py-0.5 text-xs ${
              source === "archivo"
                ? "bg-brand-100 text-brand-700"
                : "bg-slate-100 text-slate-500"
            }`}
          >
            {source === "archivo" ? "configurado en Ajustes" : "según .env"}
          </span>
        )}
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Cualquier endpoint OpenAI-compatible: el Bonsai del stack, Ollama
        (http://…:11434/v1), vLLM, LM Studio o una nube. Se aplica en caliente,
        sin reiniciar; si falla, el pipeline sigue en modo determinista.
      </p>

      <div className="mt-4 space-y-3">
        <label className="block">
          <span className="text-xs font-medium text-slate-500">URL del servidor</span>
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            spellCheck={false}
            placeholder="http://bonsai:8080/v1"
            className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 font-mono text-xs outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
          />
        </label>

        <label className="block">
          <span className="text-xs font-medium text-slate-500">Modelo</span>
          <div className="mt-1 flex gap-2">
            {modelos.length > 0 && (
              <select
                value={modelos.includes(model) ? model : ""}
                onChange={(e) => e.target.value && setModel(e.target.value)}
                className="rounded-xl border border-slate-200 px-2 py-2 text-xs"
              >
                <option value="">catálogo ({modelos.length})…</option>
                {modelos.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            )}
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              spellCheck={false}
              placeholder="ternary-bonsai-2-27b"
              className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2 font-mono text-xs outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
            />
          </div>
        </label>

        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="h-4 w-4 accent-brand-600"
          />
          LLM activo (desmarcado = modo determinista puro, sin llamadas)
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          onClick={guardar}
          disabled={busy !== null || !baseUrl.trim() || !model.trim()}
          className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {busy === "guardar" ? "Guardando…" : "Guardar"}
        </button>
        <button
          onClick={probar}
          disabled={busy !== null || !baseUrl.trim() || !model.trim()}
          className="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
        >
          {busy === "probar" ? "Probando…" : "Probar conexión"}
        </button>
        <button
          onClick={cargarCatalogo}
          disabled={busy !== null || !baseUrl.trim()}
          className="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
        >
          {busy === "catalogo" ? "Cargando…" : "Ver catálogo"}
        </button>
        {source === "archivo" && (
          <button
            onClick={restablecer}
            disabled={busy !== null}
            className="rounded-xl px-3 py-2 text-sm text-slate-500 hover:bg-slate-100"
            title={`Vuelve a: ${envDefault?.base_url ?? ""} · ${envDefault?.model ?? ""}`}
          >
            Restablecer al .env
          </button>
        )}
      </div>

      {msg && <p className="mt-3 text-sm text-emerald-700">{msg}</p>}
      {err && <p className="mt-3 text-sm text-rose-600">{err}</p>}

      {prueba && (
        <div
          className={`mt-3 rounded-xl p-3 text-sm ${
            prueba.ok
              ? "bg-emerald-50 text-emerald-800"
              : "bg-rose-50 text-rose-700"
          }`}
        >
          {prueba.ok ? (
            <>
              ✓ Respondió <span className="font-mono">{prueba.model}</span> en{" "}
              {prueba.elapsed_ms} ms{prueba.respuesta && <> — “{prueba.respuesta}”</>}
            </>
          ) : (
            <>✗ {prueba.detail || "sin respuesta"} ({prueba.elapsed_ms} ms)</>
          )}
        </div>
      )}
    </section>
  );
}
