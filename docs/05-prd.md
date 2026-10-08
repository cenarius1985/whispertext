# PRD — Plataforma WISPERTEXT (biblioteca audible de documentos)

> **Estado: 🔍 en revisión** · Fecha: 2026-10-08 · Dueño: el autor
> Documento maestro de producto: cubre toda la plataforma. Los módulos que
> crezcan (OCR, diff, export, markdown técnico) ramificarán PRDs propios.

## Problema

1. **Concentración y lectura**: el usuario tiene dificultades para sostener la
   lectura visual de documentos largos y necesita **escucharlos**; hoy lo
   resuelve con scripts sueltos (`carpeta local de materiales del autor`) sin UI, sin biblioteca
   ni continuidad.
2. **PDFs que se rompen al extraer**: al tomar texto de PDFs, los acentos quedan
   partidos y las palabras separadas/cortadas, y el TTS los lee mal o no los
   lee. Se necesita un extractor que **adapte el texto para lectura en voz
   alta**.
3. **Reproceso caro**: volver a procesar un archivo completo porque cambió un
   párrafo desperdicia recursos limitados (CPU, sin GPU). Se necesita
   reprocesamiento **incremental por párrafo**.
4. **Contenido ruido**: los PDFs traen páginas editoriales (autores, créditos,
   ISBN, legales), encabezados y pies repetidos que ensucian la escucha.
5. **Idiomas mixtos**: textos en español y en inglés; a veces se quieren oír en
   el idioma original y a veces traducidos.

## Persona / usuario objetivo

**el autor** — ingeniería clínica / del autor, usuario único y local. Lee normas
técnicas, papers y documentos institucionales (PDF digital y escaneado). PC con
recursos limitados (CPU, sin GPU). Valora: escuchar con la **voz Daniela
(es_AR)** por defecto, saber **qué párrafo está sonando**, retomar donde quedó,
y no esperar de más (priorizar lo que está por escuchar). No quiere login ni
mantenimiento complejo: `docker compose up` y listo.

## Recorrido de uso

1. **Cargar**: arrastra un PDF en la biblioteca → tarjeta nueva con estado
   "procesando" y barra de avance (SSE). Portada: sube una imagen o el sistema
   usa la página 1 del PDF; si no, solo el título.
2. **Escuchar (lector horizontal)**: entra al documento → texto a la izquierda
   con párrafos e imágenes en su posición → **click en un párrafo** (o en su
   botón play, a la derecha de cada párrafo) → ese párrafo suena y **se resalta**
   (fondo/borde) con auto-scroll suave; el panel derecho fijo muestra controles
   globales (play/pausa, anterior/siguiente, velocidad, voz) y el % avanzado.
   Puede empezar a escuchar mientras el resto del documento se sintetiza
   (prioridad on-demand).
3. **Reemplazar**: sube una versión nueva del mismo PDF → el sistema detecta el
   documento (por título/hash parcial), hace **diff de párrafos** y solo genera
   audio de los cambiados/nuevos; el lector pasa a la nueva versión conservando
   el progreso de lectura lo más cerca posible.
4. **Cambiar voz/idioma/traducir**: acción "reprocesar" → elige voz (es/en),
   velocidad o traducción es↔en → solo se sintetiza lo que la cache no cubre.
5. **Exportar**: al terminar (o cuando quiera) → "Exportar audio completo" →
   MP3 unido (mejora: M4B con capítulos) con las pausas entre párrafos.
6. **Administrar**: busca por título o por cualquier texto del contenido, ve
   estado, elimina (con confirmación, borra audios e imágenes) o reprocesa.

## Alcance

### P0 — MVP (fase 1)

| # | Requisito funcional |
|---|---|
| RF-01 | Subir PDF digital → guardado con sha256; subir exactamente el mismo archivo → aviso, sin reprocesar (modo WhatsApp). |
| RF-02 | Extracción **por párrafo** con PyMuPDF: títulos, texto e **imágenes con su caption** como bloque en la posición correcta. |
| RF-03 | Limpieza para lectura: Unicode NFC (acentos partidos), ligaduras, dehifenización de fin de línea, unión de líneas del mismo párrafo, colapso de espacios, eliminación de encabezados/pies repetidos y numeración de páginas. |
| RF-04 | Filtro editorial: saltar páginas/bloques de créditos, ISBN, legales, autores/editores (regex + Bonsai fail-soft). Los saltados se marcan y se pueden ver/reincluir desde el lector. |
| RF-05 | TTS **Piper** por párrafo; voz default `es_AR-daniela-high`; velocidad default 1.0; MP3 mono 96 kbps; cache por `(hash_texto, voz, velocidad)`. |
| RF-06 | Lector horizontal: texto izquierda + panel derecho fijo con controles globales; **botón play por párrafo a la derecha** de cada uno; click en el párrafo lo reproduce; el párrafo activo se **resalta** y hace auto-scroll. |
| RF-07 | Biblioteca: tarjetas con **portada** (imagen subida > página 1 del PDF > solo título), título, idioma, voz, estado, % leído; búsqueda por título; eliminar; reprocesar cambiando voz. |
| RF-08 | Progreso: guardar párrafo actual; al reabrir, ofrecer "continuar donde quedaste". |
| RF-09 | Jobs con estado visible (cola Redis/ARQ) y avance en tiempo real vía SSE; escucha temprana de párrafos ya listos. |
| RF-10 | Sin login/registro. Persistencia: PostgreSQL (textos/metadatos) + volumen de archivos (audios, portadas, imágenes, PDFs). Ver seguridad. |

### P1 — Incremental, OCR e idiomas (fase 2)

| # | Requisito |
|---|---|
| RF-11 | **Reemplazo de archivo**: nueva versión → diff por hash de párrafo normalizado + alineamiento → solo se sintetizan añadidos/modificados; historial de versiones visible. |
| RF-12 | **OCR Python**: páginas sin capa de texto → OCRmyPDF/Tesseract (spa+eng); indicar en el lector qué párrafos vienen de OCR. |
| RF-13 | **Imágenes**: caption con audio independiente en su posición; imagen visible en el lector; figuras sin caption se marcan `skipped`. |
| RF-14 | **Voces y idiomas**: selector es/es_AR/en; texto_hablado con expansión de siglas/números/símbolos (diccionario editable: OMS→O-M-S, unidades, referencias [12] se omiten). |
| RF-15 | **Traducción** opcional es↔en (Argos Translate local; Bonsai alternativo) al reprocesar; el original nunca se pierde. |
| RF-16 | **Export**: MP3 único (ffmpeg concat, pausa ~0.6 s entre párrafos); estado y descarga. |
| RF-17 | Búsqueda full-text del contenido (salta al párrafo encontrado). |

### P2 — Madurez (fases 3-4)

| # | Requisito |
|---|---|
| RF-18 | Export **M4B con capítulos** (por título/section) para teléfono. |
| RF-19 | **Watch folder** (p. ej. `carpeta local de materiales del autor\entrada`): auto-ingesta de PDFs nuevos. |
| RF-20 | Módulo **markdown técnico + LaTeX → texto hablado** (migrar pipeline LangChain de `texto_voz`, usando Bonsai para fórmulas). |
| RF-21 | Módulo STT opcional **Whisper light** (faster-whisper base/small): audios/videos → transcripción → documento escuchable con la voz elegida. |
| RF-22 | Soporte EPUB / DOCX / TXT. |
| RF-23 | Modo enfoque, atajos de teclado, estadísticas de escucha, detección de idioma por párrafo (docs mixtos), revertir a versión anterior, GC de audios huérfanos, backups (runbook). |

### Fuera de alcance

- Multiusuario, login, roles, nube o sincronización remota.
- Síntesis de voces clonadas (Voicebox) en el MVP — solo adapter futuro.
- Edición del texto de los párrafos (más allá de re-incluir saltados).

## Diagrama

Ver arquitectura general —
diagrama de contenedores y pipeline de 9 etapas (ingesta → extracción →
segmentación → limpieza → texto hablado → diff → TTS → estado → export).

## Casos de prueba

| # | Caso | Resultado esperado |
|---|---|---|
| 1 | Subir PDF digital nuevo | Documento `ready` (o parcialmente listo) con párrafos ordenados, títulos e imágenes en posición; audios MP3 por párrafo |
| 2 | Subir el MISMO PDF otra vez | Aviso "ya existe", 0 jobs nuevos, 0 audios generados |
| 3 | Subir versión editada (6 de 320 párrafos cambiados + 4 nuevos) | Job diff: 10 síntesis, 310 audios reutilizados; lector muestra v2; progreso conservado |
| 4 | PDF con página legal/ISBN/créditos | Esos bloques `skipped (editorial)`, sin audio, visibles/reincluibles en el lector |
| 5 | PDF con "infor-\nmación" y "cafe´" | Audio dice "información" y "café" |
| 6 | PDF escaneado | OCR spa/eng aplicado; documento escuchable; párrafos OCR etiquetados |
| 7 | PDF con figuras con caption | Caption con audio en la posición; imagen visible; figura sin caption → skipped |
| 8 | Click en párrafo 57 | Reproduce SOLO el párrafo 57, se resalta, auto-scroll; panel derecho refleja estado |
| 9 | Cambiar voz de Daniela a voz en inglés y reprocesar | Se sintetizan todos los párrafos con la nueva voz (cache miss por voz); texto intacto |
| 10 | Reprocesar tras diff de caso 3 SIN cambiar voz | Solo 10 síntesis (cache hit del resto) |
| 11 | Traducir documento en→es y reprocesar | `texto_hablado` traducido, audio en Daniela; original en inglés conservado y consultable |
| 12 | Exportar | MP3 único descargable con orden y pausas correctas (duración ≈ suma de párrafos + pausas) |
| 13 | Eliminar documento | Desaparece de biblioteca; filas y archivos (audio/imágenes/portada/PDF) borrados; audios compartidos por cache con otros documentos NO se borran |
| 14 | Bonsai apagado | Ingesta completa igual (filtro editorial conservador por regex); log del job registra `bonsai: off` |
| 15 | Cerrar y reabrir el lector | Ofrece continuar en el último párrafo escuchado |
| 16 | Buscar texto del contenido | Documento(s) que contienen el texto + salto al párrafo (P1) |
| 17 | Worker saturado y usuario avanza rápido por párrafos | Los párrafos que el usuario va a escuchar se sintetizan primero (cola high) |

## Criterios de aceptación

1. Un PDF digital típico (~50 páginas) queda **escuchable por párrafos** en
   modalidad escucha temprana antes de que termine el 100 % de la síntesis, con
   avance visible.
2. Acentos partidos y palabras cortadas del caso 5 se **leen correctamente** —
   la normalización es determinista y versionada.
3. Reemplazo de versión: **≥ 95 % de ahorro** de síntesis cuando ≤ 5 % de los
   párrafos cambian (medido en el detalle del job diff).
4. El mismo archivo subido dos veces genera **cero** audios nuevos.
5. En todo momento el lector muestra inequívocamente **qué párrafo está sonando**
   (resaltado + scroll) y cada párrafo tiene su control de audio a la derecha.
6. La biblioteca permite buscar, reprocesar (cambiar voz/idioma/traducir),
   exportar y eliminar sin dejar archivos huérfanos.
7. Todo el stack levanta con `docker compose up -d` (perfil estándar) sin pasos
   manuales beyond descarga inicial de voces; sin login.
8. Bonsai caído ≠ plataforma caída: degradación elegante verificada (caso 14).
9. Recursos: el worker sintetiza en CPU sin bloquear la UI; consumo acotado
   por límites del compose (ver entorno Docker).

## Mejoras propuestas (solicitado: "dame una mejora por si me falto algo")

| # | Mejora | Por qué |
|---|---|---|
| M-1 | **Modo enfoque** (atenúa todo salvo el párrafo activo) | Apoyo directo al problema de concentración |
| M-2 | **Retomar donde quedaste** + auto-avance continuo entre párrafos | Escucha hands-free sin perder el hilo |
| M-3 | **Prioridad on-demand + prefetch** (el siguiente párrafo se sintetiza primero) | Empezar a escuchar ya, no esperar el documento completo |
| M-4 | **Diccionario de siglas/pronunciación editable** (OMS, NR, ISO, unidades, números, omitir "[12]") | Los textos del autor están llenos de siglas: mejora masiva de comprensión al oído |
| M-5 | **Portada automática desde la página 1 del PDF** | Cumple "imagen de portada o solo el título" sin trabajo manual |
| M-6 | **Export M4B con capítulos** | Escuchar el audiolibro en el teléfono con marcadores |
| M-7 | **Watch folder** con auto-ingesta | Dejar PDFs y que aparezcan solos en la biblioteca |
| M-8 | Migrar el **pipeline markdown+LaTeX** de `texto_voz` como módulo | Ya existe y funciona con Bonsai; la tesis MRI se vuelve audiolibro |
| M-9 | Módulo **STT Whisper light** para audios/videos propios (junto a `voz/extraer_audio.py`) | Convierte material en video/voz en texto escuchable con la voz elegida |
| M-10 | Atajos de teclado (espacio, ↑/↓ párrafo, +/- velocidad) | Control sin mouse durante la escucha |
| M-11 | Detección de **idioma por párrafo** y cambio automático de voz | Abstracts en inglés dentro de docs en español, sin reprocesar todo |
| M-12 | Historial de versiones + revertir; backup programado (pg_dump + media) | Protege la biblioteca que se va acumulando |

## Preguntas abiertas (bloqueantes de detalle, no de arranque)

1. ¿Confirmas **Horizon UI** (Next.js + Tailwind) como plantilla base del frontend?
2. ¿RAM/CPU del PC? (define calidad de voces Piper high vs medium y límites del worker)
3. ¿Quieres el módulo STT Whisper light (M-9 / RF-21) dentro del alcance o queda en P2?
4. ¿Prioridad del módulo markdown+LaTeX (M-8): P1 o P2?
5. Export único: ¿MP3 (simple) y/o M4B con capítulos?
6. Traducción default: ¿Argos Translate (propuesto) o Bonsai?

## Checklist de verificación

- [x] Problema, persona, recorrido y alcance completos (P0/P1/P2/fuera de alcance).
- [x] 17 casos de prueba y 9 criterios de aceptación medibles.
- [x] 12 mejoras propuestas más allá de lo pedido.
- [x] Alineado con requisitos explícitos: dockerizado, Bonsai, ligero, Daniela
      es_AR, párrafo+resaltado, incremental "modo WhatsApp", export unido, sin
      login, biblioteca con búsqueda/portadas, saltar editorial, imágenes+caption,
      voces es/en + traducción, diff al reemplazar, OCR Python.
- [ ] Revisión y aprobación del usuario (estado 🔍 en revisión).
