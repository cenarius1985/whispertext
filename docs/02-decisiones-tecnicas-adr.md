# Decisiones técnicas (ADR) — WISPERTEXT

> **Estado: 📝 borrador**
> WISPERTEXT · Registro de decisiones de arquitectura tomadas en la
> planificación (2026-10-08). Formato: contexto → decisión → consecuencias.

## Objetivo

Dejar trazado el *porqué* de cada decisión estructural, para no re-litigarla en
la implementación y para poder revertirla consciente si cambian las condiciones.

## Alcance

Decisiones de stack y diseño del proyecto WISPERTEXT. No incluye detalles de
tablas ni de operación.

## Contenido

### ADR-001 — Motor TTS: Piper con voz default `es_AR-daniela-high`

**Contexto.** Recursos de hardware limitados (CPU, sin GPU). El usuario ya usa
Kokoro (`:8880`) y Voicebox/Qwen3-TTS (`:17493`) en `carpeta local de materiales del autor`, pero
pide algo **ligero** con la voz **Daniela (español de Argentina)**, que le gusta
como default.

**Decisión.** TTS = [Piper](https://github.com/rhasspy/piper) (neuronal, ONNX,
corre en CPU con ~500 MB de RAM y es más rápido que tiempo real).
Voz default `es_AR-daniela-high` (voz oficial Piper entrenada con OpenSLR 61;
variantes `medium`/`low` si hiciera falta aún menos recursos). Voces en inglés:
`en_US-amy-high` / `en_US-lessac-high` (a confirmar al oírlas).

**Consecuencias.**
- (+) Cumple el requisito ligero + voz exacta pedida; sin servicios de pago ni nube.
- (+) Determinista y cacheable por `(hash_texto, voz, velocidad)` → habilita el
  diff incremental (ADR-005).
- (−) Kokoro/Voicebox quedan fuera del MVP; se define un `TTSAdapter` en
  `worker/tts/` para poder enchufarlos después sin tocar el pipeline.

### ADR-002 — Base de datos: PostgreSQL (no MongoDB)

**Contexto.** El usuario preguntó qué era mejor para guardar textos de los
archivos y audios: MongoDB o Postgres.

**Decisión.** **PostgreSQL 16** para metadatos y texto; **audios como archivos
MP3 en un volumen** (`media/`), referenciados por ruta — nunca blobs en la BD.

**Justificación.**
1. El corazón del sistema es **relacional y versionado**: documento → versión →
   párrafos ordenados → audios por (voz, velocidad). Eso es un JOIN natural en
   SQL y un dolor de modelado en documentos anidados de Mongo.
2. **Búsqueda full-text nativa** (`tsvector` español/inglés + GIN) para la
   biblioteca, sin añadir Elasticsearch (recursos limitados).
3. **JSONB** cubre los casos flexibles (detalle de jobs, metadatos de extracción)
   sin perder transacciones.
4. Integridad transaccional para el diff incremental (cambiar versión + párrafos
   + jobs atómicamente).

**Consecuencias.** (+) Modelo simple, una sola pieza de infraestructura extra.
(−) Si algún día se requiere escalado masivo de escritura, habría que revisar
(irrelevante para uso personal).

### ADR-003 — LLM: Bonsai externo existente, fail-soft

**Contexto.** El usuario ya opera el LLM local **Bonsai** (`ternary-bonsai-8b`)
en el compose `stack de LLM externa` (puerto host 4687, API OpenAI-compatible), patrón ya
usado en VALIDACION-DOI2BIB.

**Decisión.** Bonsai **no** se agrega al compose de whispertext: se consume vía
`BONSAI_BASE_URL` (default `http://host.docker.internal:4687/v1`). Usos:
clasificar párrafos dudosos como editorial (JSON), apoyo opcional a traducción y
a limpieza de párrafos corruptos. Todo llamada es **fail-soft**: si no responde,
el camino determinista (regex/reglas) decide, conservador (no saltar contenido).

**Consecuencias.** (+) Cero RAM extra en el compose, reutiliza inversión
existente. (−) Si Bonsai está apagado baja la precisión del filtro editorial
(no la funcionalidad). Documentado en monitoreo de jobs (log de eventos).

### ADR-004 — Frontend Next.js (Horizon UI) + API FastAPI; Python dueño del texto

**Contexto.** Pedido explícito: "template horizont nextjs python". Horizon UI es
plantilla open-source Next.js + Tailwind. El pipeline ya es Python
(PyMuPDF/OCR/TTS) en `texto_voz`.

**Decisión.** Frontend Next.js 15 (App Router) + Tailwind con base **Horizon UI**
adaptada a layout horizontal (texto izquierda / reproductor derecha). API REST +
SSE en FastAPI. Todo el procesamiento de texto vive en Python.

**Consecuencias.** (+) Separación clara presentación vs. procesamiento;
reutilización de conocimiento Python existente. (−) Dos runtimes (node + python)
en el compose — asumido, ambos alpinizados. *Pendiente de confirmación del
usuario (pregunta abierta #1).*

### ADR-005 — Reprocesado incremental: hash por párrafo + cache de audio

**Contexto.** Requisito "modo WhatsApp": subir el mismo archivo no debe
reprocesar nada; reemplazarlo debe regenerar solo lo que cambió.

**Decisión.**
1. Dedup de archivo: `sha256` del PDF; si ya existe un documento con ese hash y
   esa configuración → no se procesa (se informa).
2. Unidad de cambio = párrafo normalizado: `hash = sha256(texto_normalizado + idioma)`.
3. Diff de versiones: alineamiento por secuencia (difflib/SequenceMatcher estilo
   patience) entre lista de hashes v(n-1) y v(n) → añadidos / eliminados /
   modificados.
4. Cache de audio: `audio_assets` con clave única `(hash_texto, voz_id, velocidad,
   formato)`; hit → reutilizar MP3 existente (incluso entre documentos).

**Consecuencias.** (+) Reemplazos baratos; export y cambio de voz solo pagan lo
que cambia (cambiar voz invalida solo la dimensión voz, no el texto). (−) El hash
depende de la calidad de la normalización: hay que congelar la versión del
normalizador (`NORMALIZER_VERSION` dentro del hash) para no invalidar caches por
bugs de limpieza.

### ADR-006 — Cola y progreso: Redis + ARQ + SSE

**Contexto.** Procesar un PDF (OCR + TTS de cientos de párrafos) tarda; la UI no
puede bloquearse y el usuario quiere ver avance y empezar a escuchar lo ya listo.

**Decisión.** Redis 7 (alpine) como cola y bus. Worker con **ARQ** (asyncio,
ligero, sin broker extra) con dos colas: `high` (párrafos on-demand/prefetch del
lector) y `default` (lotes). Progreso publicado por pub/sub y expuesto al
frontend vía **SSE** (`GET /api/events`).

**Consecuencias.** (+) Sin Celery/RabbitMQ (más liviano); el usuario puede
escuchar párrafos ya listos mientras el resto se sintetiza. (−) Redis es otra
pieza; aceptada por su doble rol (cola + eventos).

### ADR-007 — Extracción y OCR: PyMuPDF primero, Tesseract/OCRmyPDF de respaldo

**Contexto.** Pedido explícito "usa python OCR". Muchos PDFs del autor son digital
born; algunos son escaneos.

**Decisión.** Extracción primaria **PyMuPDF** (texto por bloques con posición,
fuentes e imágenes). Si una página no tiene capa de texto (o <N caracteres),
se procesa con **OCRmyPDF/Tesseract** (`spa+eng`) antes de re-extraer. Captions
de imágenes detectados por proximidad espacial + patrón
`^(Figura|Fig\.|Tabla|Imagen)\s*\d+`.

**Consecuencias.** (+) Rápido en el caso común, correcto en el escaneado.
(−) Imagen Docker del worker más pesada (tesseract + ffmpeg): ~1.5–2 GB.

### ADR-008 — Traducción local: Argos Translate (Bonsai opcional)

**Contexto.** Hay textos en inglés que el usuario quiere escuchar en español (y
viceversa), sin depender de servicios externos.

**Decisión.** Traducción determinista con **Argos Translate** local (paquete
`en↔es`, ~1 GB en el volumen `models/`), por párrafo y bajo demanda
(`reprocess` con `traducir=true`). Bonsai queda como opción alternativa
seleccionable (mejor fluidez, menos predecible).

**Consecuencias.** (+) Offline, gratuito, reproducible. (−) Calidad de
traducción técnica limitada (suficiente para lectura). El texto original SIEMPRE
se conserva: la traducción es `texto_hablado`, nunca reemplaza al original.

### ADR-009 — "Whisper light": aclaración y módulo opcional STT

**Contexto.** El nombre del proyecto es *whispertext* y el usuario menciona
"whisper es light". Whisper (OpenAI) es **STT** (voz→texto), no TTS; el TTS del
proyecto es Piper (ADR-001). En `texto_voz` existe `voz/extraer_audio.py`
(ffmpeg) para sacar audio de videos → caso de uso real de STT.

**Decisión.** El núcleo del proyecto NO depende de Whisper. Se planifica un
**módulo opcional (fase 4)** `ingestion/stt.py` con `faster-whisper`
(modelo `base` o `small`, CPU) para transcribir audios/videos propios y
convertirlos en "documentos" escuchables con la voz elegida. Queda como pregunta
abierta #3 para el usuario.

**Consecuencias.** (+) El MVP no carga el peso de un modelo STT. (−) Si el
usuario en realidad quería STT como núcleo, se reprioriza (no cambia la
arquitectura: solo otra fuente de ingesta).

## Ejemplos

Cambio de voz en un documento de 300 párrafos con 10 modificados en la última
versión: `reprocess(voice=en_US-amy-high)` → 0 hits de cache (dimensión voz
nueva) → 300 síntesis; con `reprocess(voice=es_AR-daniela-high)` tras el diff →
solo 10 síntesis nuevas.

## Checklist de verificación

- [x] 9 ADRs con contexto, decisión y consecuencias.
- [x] Alineados con requisitos del usuario (ligero, Daniela, incremental, sin login).
- [ ] ADR-001 voces en inglés confirmadas al oír.
- [ ] ADR-004 confirmación de Horizon UI (pregunta abierta).
- [ ] Revisión de usuarios: aprobar/ajustar antes de implementar.
