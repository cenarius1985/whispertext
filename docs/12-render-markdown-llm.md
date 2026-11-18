# 12 — Re-render visual con LLM (Markdown + LaTeX en el lector)

> **Estado:** Implementado y verificado E2E — 2026-11-18 (paper UTE: 361/380 bloques con markdown, tabla demográfica reconstruida, $T_2^*$ inline, 11 ecuaciones/fragmentos absorbidos por sus imágenes; 3 iteraciones de prompt+heurísticas)
> **Requisito:** RF-RND-01 · El usuario reporta que el paper científico en el
> lector se ve sin formato: ecuaciones aplastadas a texto lineal
> (`B1(t) ei 2π kz,exc(t) z dt`), números de ecuación huérfanos (`(3)`),
> tablas aplanadas a una línea y caracteres corruptos. Con GLM configurado
> (glm-5.3-flash vía Ajustes) se puede exigir al LLM orden y visualización:
> pasar el documento → Markdown enriquecido → el lector lo renderiza con
> KaTeX para las fórmulas.

## 1. Diagnóstico del caso real (paper UTE, doc a2869c8b)

- 380 bloques: 338 texto, 19 titulo, 17 ecuacion, 6 figura.
- **Ecuaciones**: las 17 tienen imagen asociada (eran gráficos en el PDF);
  `texto_latex` vacío en todas; su texto extraído es basura lineal o
  fragmentos sueltos (`(3)`, `, (6)`).
- **Tablas**: las filas llegan como líneas de texto plano
  (`Edad (años) 38.2 ± 12.6 51.8 ± 19.5 …`), ilegibles como tabla.
- **Matemática inline** en prosa aplastada (`M⊥(z) ∝ …`).
- El audio NO es el problema: 348 ready. Es puramente visual.

## 2. Diseño

**Principio rector: el párrafo sigue siendo la unidad.** No se reordena ni se
regenera nada del pipeline de audio (índices, hashes, ParagraphAudio intactos).
Se añade una **capa de presentación** paralela:

```
Paragraph.texto_md (nuevo, TEXT)  ──▶  MarkdownText (React)
   · $…$ / $$…$$  → KaTeX inline/display (katex ya es dependencia)
   · tablas Markdown → <table> centrada
   · **negrita**, *cursiva*, ### subtítulo, listas
   · ""  →  bloque oculto (fragmento basura absorbido por otro bloque)
```

- Sin `texto_md` → el lector muestra `texto` como hoy (compatibilidad total).
- El trabajo lo hace el **job `run_render_md`**: recorre los bloques activos
  de la versión actual en orden, los agrupa en **lotes de ~12 bloques /
  ~6000 chars** y le pide al LLM configurado (GLM) el Markdown limpio de
  cada bloque, devuelto como **JSON `{id: md}`** (permite tablas multilínea).
- El prompt exige: no resumir/no traducir, reparar caracteres corruptos por
  contexto, matemática en LaTeX, **juntar filas de una tabla en el primer
  bloque** (los demás quedan `""`), **vaciar números de ecuación huérfanos**.
- **Fallback determinista por bloque**: si el LLM no devuelve un id (o el
  lote falla), se aplica `fix_ligatures` + `fix_separated_accents` de
  `cleaning` y se eliminan caracteres de uso privado (PUA). El job nunca
  pierde contenido ni queda en error por culpa de un lote.
- Progreso visible: `job.hecho/total` + eventos job existentes.
- Idempotente: re-ejecutar sobreescribe `texto_md`.

**Por qué no "un Markdown gigante por documento"**: el lector sincroniza
párrafo ↔ audio (clic para escuchar, resaltado, progreso). Un render único
rompería esa relación; por bloque la conserva intacta.

## 3. Decisiones (ADR)

| # | Decisión | Por qué |
|---|----------|---------|
| D1 | Columna `paragraphs.texto_md` (ALTER … IF NOT EXISTS, patrón init_db) | create_all no altera; ya hay precedente de columnas a mano. |
| D2 | LLM por lotes JSON, no por párrafo | 380 bloques → ~32 llamadas; el contexto del lote permite juntar tablas/fórmulas partidas entre bloques consecutivos. |
| D3 | Ecuaciones con imagen: `texto_md=""` (la imagen ya contiene la fórmula); con `texto_latex`: `$$latex$$` | Las 17 del caso real tienen imagen; el texto extraído es basura. |
| D4 | Renderer Markdown propio (~120 líneas, katex incluido) sin deps nuevas | El proyecto tiene 4 deps frontend; react-markdown+remark-math+rehype-katex pesan más que lo que se necesita. Entrada SIEMPRE escapada; el único HTML generado es el propio + KaTeX. |
| D5 | Figuras/ecuaciones-imagen pasan a layout centrado (imagen arriba, caption abajo) | Hoy compiten en la fila flex con el texto: "imágenes desordenadas". |
| D6 | Botón "Mejorar visualización (IA)" en el lector y en el menú ⋯ | Opt-in por documento: el paso cuesta llamadas LLM y no todos los docs lo necesitan. |
| D7 | Timeout propio `render_llm_timeout_s=120` por lote, 1 reintento | Lotes grandes con tablas tardan; distinto del timeout de fórmulas sueltas. |

## 4. Fases

### Fase 1 — Worker
- [x] `models.py`: `Paragraph.texto_md`; `db.py`: ALTER idempotente.
- [x] `worker/render_md.py`: prompt + lotes + parseo JSON + fallback
  determinista (reusa `cleaning`) + escritura por lote con progreso.
- [x] `jobs.py`: `run_render_md` (valida doc, marca hecho/total, fail-soft);
  registro en arq (`worker/main.py`).
- [x] `config.py`: `render_llm_timeout_s`.

### Fase 2 — API
- [x] `ParagraphOut.texto_md`.
- [x] `POST /api/documents/{id}/render_md` → job 202 (como /export).

### Fase 3 — Frontend
- [x] `components/MarkdownText.tsx`: markdown mínimo + KaTeX inline/display
  + tablas + énfasis + listas; escape previo.
- [x] `ReaderView`: render con `texto_md ?? texto`; layout centrado para
  figura/ecuacion-imagen; ocultar bloques con `texto_md === ""`.
- [x] Botón "Mejorar visualización (IA)" (PlayerPanel + menú ⋯) con estado
  de progreso; al terminar (`job done` via eventos) recarga párrafos.

### Fase 4 — Docs, build y pruebas
- [x] Este documento + README.
- [x] Rebuild api/worker/frontend; E2E sobre el paper UTE real; commit+push.

## 5. Riesgos

- **Alucinación de contenido**: mitigado por prompt estricto + fallback por
  bloque; el `texto` original nunca se sobreescribe (siempre recuperable).
- **Coste/tiempo LLM**: lotes + opt-in por documento; ~32 llamadas flash
  para un paper, ~160 para la tesis completa.
- **Markdown mal formado del LLM**: el renderer es tolerante (lo que no
  reconoce lo muestra como texto escapado).

## 6. Iteración E2E (lecciones de la prueba real)

1. **Tablas aplanadas**: el LLM no juntó filas separadas por bloques
   intercalados (PDF a dos columnas). Solución determinista: detector de
   filas `«etiqueta A ± B C ± D»` + agrupación por página/cercanía → tabla
   Markdown armada sin LLM (docs/12, `render_md.tabla_de_filas`).
2. **Matemática inline**: el LLM envolvía poco. Post-toque determinista
   `matizar_inline` (T2∗ → $T_2^{*}$, R1 → $R_1$) sobre la salida.
3. **Ecuaciones**: la imagen ya contiene la fórmula → `texto_md=""`
   (el texto extraído lineal era irrecuperable).
4. `selectinload(Paragraph.imagen)` obligatorio en el job (lazy load en
   async → MissingGreenlet).
