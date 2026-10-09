export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface CategoryRef {
  id: string;
  nombre: string;
  color: string;
  icono: string;
  es_sistema: boolean;
}

export interface Category extends CategoryRef {
  total: number;
}

export interface Doc {
  id: string;
  titulo: string;
  autor: string | null;
  formato: string;
  estado: string;
  idioma_origen: string;
  idioma_lectura: string;
  voz_clave: string | null;
  velocidad: number;
  version_actual: number;
  total_parrafos_activos: number;
  portada_url: string | null;
  progreso_indice: number | null;
  duracion_total_seg: number;
  categorias: CategoryRef[];
  error: string | null;
}

export interface Paragraph {
  id: string;
  indice: number;
  pagina: number;
  tipo: string;
  texto: string;
  latex?: string | null;
  estado_audio: string;
  skip_reason: string | null;
  audio_url: string | null;
  imagen_url: string | null;
}

export interface Voice {
  id: string;
  clave: string;
  nombre: string;
  idioma: string;
  calidad: string;
  es_default: boolean;
}

export interface ExportRow {
  id: string;
  formato: string;
  estado: string;
  download_url: string | null;
  duracion_total_seg: number;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (body?.detail?.message) detail = body.detail.message;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function fetchDocs(q?: string, categoriaId?: string): Promise<Doc[]> {
  const url = new URL(`${API_URL}/api/documents`);
  if (q) url.searchParams.set("q", q);
  if (categoriaId) url.searchParams.set("categoria_id", categoriaId);
  return json(await fetch(url.toString(), { cache: "no-store" }));
}

export async function fetchCategories(): Promise<Category[]> {
  return json(await fetch(`${API_URL}/api/categories`, { cache: "no-store" }));
}

export async function createCategory(
  nombre: string,
  color?: string,
  icono?: string
): Promise<Category> {
  return json(
    await fetch(`${API_URL}/api/categories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nombre, color, icono }),
    })
  );
}

export async function updateCategory(
  id: string,
  opts: { nombre?: string; color?: string; icono?: string }
): Promise<void> {
  await json(
    await fetch(`${API_URL}/api/categories/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opts),
    })
  );
}

export async function deleteCategory(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/categories/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("no se pudo eliminar la categoría");
}

export async function fetchDoc(id: string): Promise<Doc> {
  return json(await fetch(`${API_URL}/api/documents/${id}`, { cache: "no-store" }));
}

export async function fetchParagraphs(id: string): Promise<Paragraph[]> {
  return json(
    await fetch(`${API_URL}/api/documents/${id}/paragraphs`, { cache: "no-store" })
  );
}

export async function fetchVoices(): Promise<Voice[]> {
  return json(await fetch(`${API_URL}/api/voices`, { cache: "no-store" }));
}

export async function fetchExports(id: string): Promise<ExportRow[]> {
  return json(await fetch(`${API_URL}/api/documents/${id}/exports`, { cache: "no-store" }));
}

export async function uploadDocument(file: File, voz?: string): Promise<Doc> {
  const fd = new FormData();
  fd.append("archivo", file);
  const qs = voz ? `?voz_clave=${encodeURIComponent(voz)}` : "";
  return json(
    await fetch(`${API_URL}/api/documents${qs}`, { method: "POST", body: fd })
  );
}

export async function replaceDocument(id: string, file: File): Promise<void> {
  const fd = new FormData();
  fd.append("archivo", file);
  await json(
    await fetch(`${API_URL}/api/documents/${id}/replace`, { method: "POST", body: fd })
  );
}

export async function reprocessDocument(
  id: string,
  opts: { voz_clave?: string; velocidad?: number; traducir?: boolean; idioma_lectura?: string }
): Promise<void> {
  await json(
    await fetch(`${API_URL}/api/documents/${id}/reprocess`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opts),
    })
  );
}

export async function exportDocument(id: string): Promise<void> {
  await json(
    await fetch(`${API_URL}/api/documents/${id}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ formato: "mp3" }),
    })
  );
}

export async function renameDocument(id: string, titulo: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/documents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ titulo }),
  });
  if (!res.ok) throw new Error("no se pudo renombrar");
}

export async function setDocCategories(id: string, categoryIds: string[]): Promise<void> {
  const res = await fetch(`${API_URL}/api/documents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category_ids: categoryIds }),
  });
  if (!res.ok) {
    let detail = "no se pudieron guardar las categorías";
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {}
    throw new Error(detail);
  }
}

export async function deleteDocument(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/documents/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error("no se pudo eliminar");
}

export async function uploadCover(id: string, file: File): Promise<void> {
  const fd = new FormData();
  fd.append("imagen", file);
  await json(await fetch(`${API_URL}/api/documents/${id}/cover`, { method: "POST", body: fd }));
}

export async function saveProgress(id: string, paragraphId: string): Promise<void> {
  await fetch(`${API_URL}/api/documents/${id}/progress`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paragraph_id: paragraphId }),
  });
}

export async function synthesizeParagraph(paragraphId: string): Promise<void> {
  await fetch(`${API_URL}/api/paragraphs/${paragraphId}/synthesize`, { method: "POST" });
}

export function mediaUrl(path: string | null): string {
  return path ? `${API_URL}${path}` : "";
}

export const ESTADOS: Record<string, { label: string; cls: string }> = {
  pending: { label: "En cola", cls: "bg-slate-100 text-slate-600" },
  extracting: { label: "Extrayendo", cls: "bg-amber-100 text-amber-700" },
  cleaning: { label: "Limpiando", cls: "bg-amber-100 text-amber-700" },
  synthesizing: { label: "Sintetizando", cls: "bg-blue-100 text-blue-700" },
  ready: { label: "Listo", cls: "bg-emerald-100 text-emerald-700" },
  error: { label: "Error", cls: "bg-rose-100 text-rose-700" },
};

export const FORMATOS: Record<string, { label: string; cls: string }> = {
  pdf: { label: "PDF", cls: "bg-rose-500/90 text-white" },
  docx: { label: "DOCX", cls: "bg-blue-600/90 text-white" },
  epub: { label: "EPUB", cls: "bg-emerald-600/90 text-white" },
  html: { label: "HTML", cls: "bg-orange-500/90 text-white" },
  txt: { label: "TXT", cls: "bg-slate-500/90 text-white" },
  md: { label: "MD", cls: "bg-violet-500/90 text-white" },
};

export const ACCEPT_UPLOAD =
  ".pdf,.txt,.text,.md,.docx,.html,.htm,.epub";

export const PALETA = [
  "#6366f1", "#0ea5e9", "#10b981", "#f59e0b",
  "#ef4444", "#ec4899", "#8b5cf6", "#64748b",
];

export const ICONOS = [
  "📁", "🏥", "🎓", "📄", "🔬", "⚖️", "💼", "🎧",
  "🧪", "📊", "🌐", "⭐",
];

export function duracionLegible(seg: number): string {
  if (!seg || seg <= 0) return "—";
  const h = Math.floor(seg / 3600);
  const m = Math.round((seg % 3600) / 60);
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
}
