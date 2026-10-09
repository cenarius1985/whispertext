# PRD — Actualización v2: multi-formato, categorías y nueva biblioteca visual

> Estado: ✅ aprobado e implementado (2026-10-09) · ramas `gpu` y `feature/multiformato-categorias`, integradas a `main`

PRD ramificado del [PRD maestro](05-prd.md). Cubre la evolución de "conversor
PDF→audio" a **biblioteca audible completa**: más formatos de origen,
organización por categorías y una UI de biblioteca con sidebar. Requisitos con
prefijos: **RF-MF** (multi-formato), **RF-CAT** (categorías), **RF-UI** (visual).

## Problema

1. **Solo PDF**: las normas y documentos también llegan en Word (.docx), HTML,
   EPUB y texto plano (.txt/.md). La API los rechazaba con 415.
2. **Biblioteca plana**: sin categorías ni filtros laterales, encontrar "las
   normas" o "los papers de tesis" exigía buscar a ciegas.
3. **UI minimalista**: faltaban señales de formato, progreso por tarjeta, vista
   compacta y navegación por estantes (sidebar).

## Recorrido de uso

1. **Cargar cualquier formato**: arrastra un .docx → tarjeta con badge **DOCX**,
   portada generada y el pipeline familiar (SSE → escucha temprana). Un .epub
   trae su **portada real** y sus capítulos como títulos de sección.
2. **Organizar**: en la tarjeta → "Organizar" → asigna **MINSAL** y **Normas**
   (multi-categoría) y crea la que falta al vuelo. El **sidebar** muestra las
   categorías con color, icono y contador.
3. **Filtrar y ordenar**: clic en una categoría → filtra al instante (combina
   con búsqueda). Vista **lista** ordenable (reciente/título/duración).
4. **Escuchar**: lector con breadcrumb `Biblioteca › categoría › título`.

## Alcance

### F-A — Multi-formato (backend)

| # | Requisito |
|---|---|
| RF-MF-01 | Aceptar `.pdf .txt .text .md .docx .html .htm .epub`; dedup por sha256 y diff incremental **idénticos a PDF**. |
| RF-MF-02 | Dispatcher `extract_any(path)` produce el **mismo `ExtractionResult`** que el PDF → limpieza, normalizador, ecuaciones (Bonsai), TTS y cache quedan intactos. |
| RF-MF-03 | **TXT**: párrafos por línea vacía; títulos por mayúsculas. |
| RF-MF-04 | **MD**: `#` → títulos; bloques de código y tablas markdown → tipo `codigo` (se muestran, no se leen). |
| RF-MF-05 | **DOCX** (python-docx): Heading→título, imágenes→figura (la 1ª es portada), tablas→texto por filas. |
| RF-MF-06 | **HTML** (bs4+lxml): descarta nav/scripts/etc.; `<figure>` asocia img+figcaption; tablas→filas; data: URIs→imágenes. |
| RF-MF-07 | **EPUB** (zipfile+OPF): capítulos del spine en orden, dc:title/creator, cover-image real. |
| RF-MF-08 | Columna `documents.formato` (ALTER IF NOT EXISTS). |
| RF-MF-09 | Portadas: PDF pág. 1 · EPUB cover OPF · DOCX 1ª imagen · resto placeholder en frontend. |

### F-B — Categorías (N:M)

| # | Requisito |
|---|---|
| RF-CAT-01 | `categories(id, nombre UNIQUE, color, icono, es_sistema)` + `document_categories` N:M. |
| RF-CAT-02/03 | CRUD `/api/categories` (409 duplicados; DELETE no borra documentos; las de sistema no se editan). |
| RF-CAT-04 | `PATCH /api/documents/{id}` acepta `category_ids` (reemplazo completo). |
| RF-CAT-05 | `GET /api/documents?categoria_id=` combinable con `?q=`. |
| RF-CAT-06 | Categoría de sistema **⭐ Favoritos** (sembrada, protegida). |
| RF-CAT-07 | Migración sin dolor: `create_all` crea las tablas; nada que migrar. |

### F-C — UI

| # | Requisito |
|---|---|
| RF-UI-01 | Sidebar: búsqueda, "Todas" + categorías (icono/color/contador), creación inline (paleta + emojis), stats. |
| RF-UI-02 | Filtro instantáneo combinable; URL `?cat=` compartible. |
| RF-UI-03 | Tarjeta: badge de formato, chips de categoría navegables, barra de % leído, estrella favorito. |
| RF-UI-04 | Modal "Organizar" (asignar/crear con color e icono). |
| RF-UI-05 | Vista grid/lista + orden persistidos en localStorage. |
| RF-UI-06 | Breadcrumb en el lector. |
| RF-UI-07 | Subida/dropzone/replace aceptan todos los formatos. |

## Casos de prueba (extracto)

| # | Caso | Esperado |
|---|---|---|
| 1-5 | Subir txt/md/docx/html/epub de prueba | bloques correctos (títulos, figuras, capítulos, tablas por filas) — cubierto por `tests/test_extractors.py` |
| 6 | Re-subir el mismo archivo | 409 dedup |
| 7 | Reemplazo docx v2 con 1 párrafo cambiado | solo eso se re-sintetiza (diff intacto) |
| 8 | Subir `.xyz` | 415 |
| 9-13 | CRUD categorías, N:M, contadores, Favoritos, filtros | verificado E2E |
| 15 | **Regresión PDF** | comportamiento idéntico al anterior |

## Criterios de aceptación — resultado

- ✅ 51/51 tests backend (7 nuevos de extractores + 7 de llm_runtime).
- ✅ 29/29 checks E2E contra la API real.
- ✅ PDF sin regresión (pipeline intacto por diseño del dispatcher).
- ✅ Docker build sin romper el existente; stack levanta con `python coordinador.py`.

## Decisiones resueltas al implementar

1. **N:M** (colecciones estilo Audible/calibre) · 2. icono+color por categoría ·
3. tablas .docx leídas como texto por filas · 4. biblioteca única con sidebar.
