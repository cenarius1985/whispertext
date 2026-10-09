"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ACCEPT_UPLOAD,
  Category,
  Doc,
  PALETA,
  ICONOS,
  createCategory,
  deleteCategory,
  duracionLegible,
  fetchCategories,
  fetchDocs,
  setDocCategories,
  updateCategory,
  uploadDocument,
} from "@/lib/api";
import { useDocumentEvents } from "@/lib/useDocumentEvents";
import DocumentCard from "@/components/DocumentCard";

type Orden = "reciente" | "titulo" | "duracion";

function useLocalStorage<T>(key: string, inicial: T) {
  const [valor, setValor] = useState<T>(inicial);
  useEffect(() => {
    const guardado = window.localStorage.getItem(key);
    if (guardado !== null) {
      try {
        setValor(JSON.parse(guardado) as T);
      } catch {}
    }
  }, [key]);
  const set = (v: T) => {
    setValor(v);
    window.localStorage.setItem(key, JSON.stringify(v));
  };
  return [valor, set] as const;
}

export default function BibliotecaPage() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [cats, setCats] = useState<Category[]>([]);
  const [q, setQ] = useState("");
  const [catActiva, setCatActiva] = useState<string | null>(null);
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [organizando, setOrganizando] = useState<Doc | null>(null);
  const [vista, setVista] = useLocalStorage<"grid" | "lista">("wt.vista", "grid");
  const [orden, setOrden] = useLocalStorage<Orden>("wt.orden", "reciente");
  const inputRef = useRef<HTMLInputElement>(null);

  // categoría activa desde la URL (?cat=) al montar
  useEffect(() => {
    const cat = new URLSearchParams(window.location.search).get("cat");
    if (cat) setCatActiva(cat);
  }, []);

  const sincronizarUrl = useCallback((cat: string | null) => {
    const url = new URL(window.location.href);
    if (cat) url.searchParams.set("cat", cat);
    else url.searchParams.delete("cat");
    window.history.replaceState(null, "", url.toString());
  }, []);

  const recargar = useCallback(async () => {
    try {
      const [docs_, cats_] = await Promise.all([
        fetchDocs(q || undefined, catActiva ?? undefined),
        fetchCategories(),
      ]);
      setDocs(docs_);
      setCats(cats_);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [q, catActiva]);

  useEffect(() => {
    const t = setTimeout(() => recargar(), 250);
    return () => clearTimeout(t);
  }, [recargar]);

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

  const elegirCategoria = (id: string | null) => {
    setCatActiva(id);
    sincronizarUrl(id);
  };

  const procesando = docs.some((d) =>
    ["pending", "extracting", "cleaning", "synthesizing"].includes(d.estado)
  );

  const docsOrdenados = [...docs].sort((a, b) => {
    if (orden === "titulo") return a.titulo.localeCompare(b.titulo, "es");
    if (orden === "duracion") return (b.duracion_total_seg || 0) - (a.duracion_total_seg || 0);
    return 0 // "reciente" ya viene ordenado del backend
  });

  const totalHoras = docs.reduce((s, d) => s + (d.duracion_total_seg || 0), 0);
  const favId = cats.find((c) => c.es_sistema)?.id ?? null;

  return (
    <div className="flex gap-6">
      {/* ---------------- Sidebar ---------------- */}
      <aside className="hidden w-60 shrink-0 lg:block">
        <div className="sticky top-20 space-y-5">
          <div className="relative">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar…"
              className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
            />
          </div>

          <nav className="space-y-0.5 text-sm">
            <button
              onClick={() => elegirCategoria(null)}
              className={`flex w-full items-center justify-between rounded-lg px-3 py-1.5 ${
                catActiva === null
                  ? "bg-brand-50 font-medium text-brand-700"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              <span>📚 Todas</span>
              <span className="text-xs text-slate-400">{cats.length ? docs.length : ""}</span>
            </button>
            {cats.map((c) => (
              <div key={c.id} className="group/cat flex items-center">
                <button
                  onClick={() => elegirCategoria(c.id)}
                  className={`flex flex-1 items-center gap-2 truncate rounded-lg px-3 py-1.5 text-left ${
                    catActiva === c.id
                      ? "bg-brand-50 font-medium text-brand-700"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  <span>{c.icono}</span>
                  <span className="truncate">{c.nombre}</span>
                  <span
                    className="ml-auto h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: c.color }}
                  />
                  <span className="shrink-0 text-xs text-slate-400">{c.total}</span>
                </button>
                {!c.es_sistema && (
                  <button
                    title="Renombrar categoría"
                    onClick={async () => {
                      const nuevo = window.prompt("Renombrar categoría:", c.nombre);
                      if (nuevo && nuevo.trim() && nuevo.trim() !== c.nombre) {
                        try {
                          await updateCategory(c.id, { nombre: nuevo.trim() });
                          recargar();
                        } catch (e) {
                          window.alert((e as Error).message);
                        }
                      }
                    }}
                    className="hidden px-1 text-xs text-slate-400 hover:text-brand-600 group-hover/cat:block"
                  >
                    ✎
                  </button>
                )}
                {!c.es_sistema && (
                  <button
                    title="Eliminar categoría (los documentos no se borran)"
                    onClick={async () => {
                      if (!window.confirm(`¿Eliminar la categoría “${c.nombre}”? Los documentos NO se eliminan.`)) return;
                      try {
                        await deleteCategory(c.id);
                        if (catActiva === c.id) elegirCategoria(null);
                        else recargar();
                      } catch (e) {
                        window.alert((e as Error).message);
                      }
                    }}
                    className="hidden px-1 text-xs text-slate-400 hover:text-rose-600 group-hover/cat:block"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <NuevaCategoriaInline onCreada={(c) => { setCats((prev) => [...prev, c].sort((a,b)=> (b.es_sistema?1:0)-(a.es_sistema?1:0) || a.nombre.localeCompare(b.nombre,"es"))); }} />
          </nav>

          <div className="rounded-xl bg-white px-4 py-3 text-xs text-slate-500 ring-1 ring-slate-200">
            <p className="font-medium text-slate-700">Biblioteca</p>
            <p>{docs.length} documento{docs.length === 1 ? "" : "s"} visible{docs.length === 1 ? "" : "s"}</p>
            <p>{duracionLegible(totalHoras)} de audio</p>
            {procesando && <p className="mt-1 text-brand-600">procesando… (en vivo)</p>}
          </div>
        </div>
      </aside>

      {/* ---------------- Contenido ---------------- */}
      <div className="min-w-0 flex-1 space-y-6">
        <section className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">
              {catActiva && cats.find((c) => c.id === catActiva)
                ? `${cats.find((c) => c.id === catActiva)!.icono} ${cats.find((c) => c.id === catActiva)!.nombre}`
                : "Biblioteca"}
            </h1>
            <p className="text-sm text-slate-500">
              {docs.length} documento{docs.length === 1 ? "" : "s"}
              {catActiva && (
                <button onClick={() => elegirCategoria(null)} className="ml-2 text-brand-600 hover:underline">
                  quitar filtro
                </button>
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex overflow-hidden rounded-xl ring-1 ring-slate-200">
              <button
                onClick={() => setVista("grid")}
                className={`px-3 py-2 text-sm ${vista === "grid" ? "bg-brand-600 text-white" : "bg-white text-slate-500 hover:bg-slate-50"}`}
                title="Vista de portadas"
              >
                ▦
              </button>
              <button
                onClick={() => setVista("lista")}
                className={`px-3 py-2 text-sm ${vista === "lista" ? "bg-brand-600 text-white" : "bg-white text-slate-500 hover:bg-slate-50"}`}
                title="Vista de lista"
              >
                ☰
              </button>
            </div>
            <select
              value={orden}
              onChange={(e) => setOrden(e.target.value as Orden)}
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600"
            >
              <option value="reciente">Recientes</option>
              <option value="titulo">Título</option>
              <option value="duracion">Duración</option>
            </select>
            <button
              onClick={() => inputRef.current?.click()}
              disabled={subiendo}
              className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white shadow hover:bg-brand-700 disabled:opacity-50"
            >
              {subiendo ? "Subiendo…" : "+ Subir documento"}
            </button>
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT_UPLOAD}
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
          className="rounded-2xl border-2 border-dashed border-slate-200 p-3 text-center text-sm text-slate-400"
        >
          Arrastra PDF · Word · EPUB · HTML · TXT · MD para agregarlos a la biblioteca
        </div>

        {docs.length === 0 ? (
          <p className="py-16 text-center text-slate-400">
            {catActiva
              ? "Sin documentos en esta categoría todavía."
              : "Aún no hay documentos. Sube el primero con “+ Subir documento”."}
          </p>
        ) : vista === "grid" ? (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {docsOrdenados.map((d) => (
              <DocumentCard
                key={d.id}
                doc={d}
                onChanged={recargar}
                onOrganize={() => setOrganizando(d)}
                onFilterCat={(cid) => elegirCategoria(cid)}
                favId={favId}
              />
            ))}
          </div>
        ) : (
          <div className="overflow-hidden rounded-2xl bg-white ring-1 ring-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-4 py-3">Documento</th>
                  <th className="px-4 py-3">Formato</th>
                  <th className="px-4 py-3">Categorías</th>
                  <th className="px-4 py-3">Duración</th>
                  <th className="px-4 py-3">Leído</th>
                </tr>
              </thead>
              <tbody>
                {docsOrdenados.map((d) => (
                  <ListaRow
                    key={d.id}
                    doc={d}
                    onChanged={recargar}
                    onOrganize={() => setOrganizando(d)}
                    onFilterCat={(cid) => elegirCategoria(cid)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {organizando && (
        <OrganizarModal
          doc={organizando}
          categorias={cats}
          onClose={() => setOrganizando(null)}
          onSaved={() => {
            setOrganizando(null);
            recargar();
          }}
        />
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Crear categoría inline en el sidebar                                       */
/* -------------------------------------------------------------------------- */

function NuevaCategoriaInline({ onCreada }: { onCreada: (c: Category) => void }) {
  const [abierto, setAbierto] = useState(false);
  const [nombre, setNombre] = useState("");
  const [color, setColor] = useState(PALETA[0]);
  const [icono, setIcono] = useState(ICONOS[0]);
  const [busy, setBusy] = useState(false);

  if (!abierto) {
    return (
      <button
        onClick={() => setAbierto(true)}
        className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-slate-400 hover:bg-slate-100 hover:text-brand-600"
      >
        <span className="text-base leading-none">+</span> Nueva categoría
      </button>
    );
  }
  return (
    <div className="mt-1 space-y-2 rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
      <input
        autoFocus
        value={nombre}
        onChange={(e) => setNombre(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && nombre.trim() && crear()}
        placeholder="Nombre de la categoría"
        className="w-full rounded-lg border border-slate-200 px-2 py-1 text-sm outline-none focus:border-brand-500"
      />
      <div className="flex flex-wrap gap-1">
        {ICONOS.map((ic) => (
          <button
            key={ic}
            onClick={() => setIcono(ic)}
            className={`h-7 w-7 rounded-md text-sm ${icono === ic ? "ring-2 ring-brand-500" : "hover:bg-white"}`}
          >
            {ic}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {PALETA.map((c) => (
          <button
            key={c}
            onClick={() => setColor(c)}
            className={`h-5 w-5 rounded-full ${color === c ? "ring-2 ring-slate-800 ring-offset-1" : ""}`}
            style={{ backgroundColor: c }}
          />
        ))}
      </div>
      <div className="flex gap-2">
        <button
          disabled={busy || !nombre.trim()}
          onClick={crear}
          className="flex-1 rounded-lg bg-brand-600 px-2 py-1.5 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {busy ? "Creando…" : "Crear"}
        </button>
        <button
          onClick={() => { setAbierto(false); setNombre(""); }}
          className="rounded-lg px-2 py-1.5 text-xs text-slate-500 hover:bg-white"
        >
          Cancelar
        </button>
      </div>
    </div>
  );

  async function crear() {
    if (!nombre.trim()) return;
    setBusy(true);
    try {
      const c = await createCategory(nombre.trim(), color, icono);
      onCreada(c);
      setNombre("");
      setAbierto(false);
    } catch (e) {
      window.alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
}

/* -------------------------------------------------------------------------- */
/* Modal organizar: asignar/crear categorías del documento                    */
/* -------------------------------------------------------------------------- */

function OrganizarModal({
  doc,
  categorias,
  onClose,
  onSaved,
}: {
  doc: Doc;
  categorias: Category[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [sel, setSel] = useState<Set<string>>(
    new Set(doc.categorias.map((c) => c.id))
  );
  const [busy, setBusy] = useState(false);
  const [nombreNueva, setNombreNueva] = useState("");

  const toggle = (id: string) =>
    setSel((prev) => {
      const s = new Set(prev);
      if (s.has(id)) s.delete(id);
      else s.add(id);
      return s;
    });

  const crearYAsignar = async () => {
    if (!nombreNueva.trim()) return;
    setBusy(true);
    try {
      const c = await createCategory(nombreNueva.trim());
      setSel((prev) => new Set(prev).add(c.id));
      setNombreNueva("");
    } catch (e) {
      window.alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const guardar = async () => {
    setBusy(true);
    try {
      await setDocCategories(doc.id, Array.from(sel));
      onSaved();
    } catch (e) {
      window.alert((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-md space-y-4 rounded-2xl bg-white p-5 shadow-xl">
        <div>
          <h2 className="font-semibold text-slate-900">Organizar</h2>
          <p className="line-clamp-1 text-sm text-slate-500">{doc.titulo}</p>
        </div>

        <div className="max-h-64 space-y-1 overflow-y-auto">
          {categorias.map((c) => (
            <label
              key={c.id}
              className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm hover:bg-slate-50"
            >
              <input
                type="checkbox"
                checked={sel.has(c.id)}
                onChange={() => toggle(c.id)}
                className="h-4 w-4 accent-brand-600"
              />
              <span>{c.icono}</span>
              <span className="flex-1 text-slate-700">{c.nombre}</span>
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: c.color }} />
            </label>
          ))}
        </div>

        <div className="flex gap-2">
          <input
            value={nombreNueva}
            onChange={(e) => setNombreNueva(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && crearYAsignar()}
            placeholder="+ Crear y asignar nueva…"
            className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-500"
          />
          <button
            disabled={busy || !nombreNueva.trim()}
            onClick={crearYAsignar}
            className="rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-600 hover:bg-slate-200 disabled:opacity-50"
          >
            Crear
          </button>
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-slate-500 hover:bg-slate-100">
            Cancelar
          </button>
          <button
            disabled={busy}
            onClick={guardar}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {busy ? "Guardando…" : "Guardar"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Fila de la vista lista                                                     */
/* -------------------------------------------------------------------------- */

function ListaRow({
  doc,
  onChanged,
  onOrganize,
  onFilterCat,
}: {
  doc: Doc;
  onChanged: () => void;
  onOrganize: () => void;
  onFilterCat: (cid: string) => void;
}) {
  const progreso =
    doc.progreso_indice != null && doc.total_parrafos_activos > 0
      ? Math.round(((doc.progreso_indice + 1) / doc.total_parrafos_activos) * 100)
      : 0;
  return (
    <tr className="border-b border-slate-50 last:border-0 hover:bg-slate-50/60">
      <td className="px-4 py-3">
        <a href={`/lector/${doc.id}`} className="font-medium text-slate-800 hover:text-brand-600">
          {doc.titulo}
        </a>
        {doc.autor && <p className="text-xs text-slate-400">{doc.autor}</p>}
      </td>
      <td className="px-4 py-3">
        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
          {(doc.formato || "pdf").toUpperCase()}
        </span>
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {doc.categorias.map((c) => (
            <button
              key={c.id}
              onClick={() => onFilterCat(c.id)}
              className="rounded-full px-2 py-0.5 text-xs hover:opacity-80"
              style={{ backgroundColor: `${c.color}1a`, color: c.color }}
            >
              {c.icono} {c.nombre}
            </button>
          ))}
          <button onClick={onOrganize} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 hover:bg-slate-200">
            + organizar
          </button>
        </div>
      </td>
      <td className="px-4 py-3 text-slate-500">{duracionLegible(doc.duracion_total_seg)}</td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-brand-500" style={{ width: `${progreso}%` }} />
          </div>
          <span className="text-xs text-slate-400">{progreso}%</span>
        </div>
      </td>
    </tr>
  );
}
