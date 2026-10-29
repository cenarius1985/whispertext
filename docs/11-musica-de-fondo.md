# 11 — Música de fondo en los exports (desde YouTube)

> **Estado:** Implementado y verificado E2E — 2026-10-29 (mezcla 5 min con música de YouTube: bucle cubre 302.9 s, pausas llenas de música, descarga "(con música).mp3")
> **Requisito:** RF-MUS-01 · El usuario pidió: poder pegar una canción o playlist
> de YouTube como música de fondo del audiolibro; si no cubre toda la duración,
> se repite en bucle; botón "Editar audio" que abre una página dedicada a esta
> configuración; el resultado se mezcla con la voz y se descarga.

## 1. Objetivo y experiencia de usuario

Desde la biblioteca o el lector, un botón **"Editar audio"** lleva a la página
`/editar-audio?doc=<id>`, un "estudio" del documento donde se:

1. ve la duración del audio base (voz) del documento;
2. pega la **URL de YouTube** (canción suelta o playlist completa);
3. ajusta el **volumen de la música** (control deslizante en dB bajo la voz);
4. pulsa **"Crear y descargar"** → diálogo con progreso por etapas
   (descargando música → mezclando → listo) → **descarga automática** del MP3;
5. consulta el **historial** de exports del documento (con y sin música) y
   re-descarga cualquiera.

La música queda por **debajo de la voz con ducking** (baja sola mientras habla
el narrador, recupera nivel en las pausas) — la misma receta ya probada en
`D:\GitHub\MRI\Presentacion-iHealth\src\musica.py`.

## 2. Decisiones técnicas (estilo ADR)

| # | Decisión | Por qué |
|---|----------|---------|
| D1 | **yt-dlp dentro del worker** (pip, imagen Docker) | Es el motor que sigue funcionando en 2026 (SABR/PoToken rompe pytube). El contenedor comparte la IP residencial del host, donde ya se probó que descarga. |
| D2 | **Solo audio** (`-f bestaudio -x`), re-encode a MP3 160k uniforme | No baja video; pistas uniformes 44.1 kHz estéreo permiten concat `-c copy` sin errores. |
| D3 | **Cache por hash de URL** en `/data/media/music/<sha16>/pista.mp3` | Re-exportar o probar volúmenes distintos no re-descarga la música. |
| D4 | **Mezcla con ducking ffmpeg** (`sidechaincompress` + `amix duration=first normalize=0` + `alimiter`) | Calidad probada (referencia iHealth). `normalize=0` no aplasta la voz. |
| D5 | **Bucle con `-stream_loop -1`** sobre la pista de música + `amix duration=first` y `-t <dur_voz>` | Si la música no cubre, se repite hasta cubrir exacto; el output termina donde termina la voz. |
| D6 | **Playlist → concat** de hasta **30 pistas** (`--playlist-end 30`) en orden de lista | Tope de sanidad (tamaño/descarga); la playlist concatenada es "la pista" que luego se buclea. |
| D7 | `exports.formato = "mp3m"` para distinguir | La columna es `String(8)`; evitar migración de esquema. El MP3 sigue siendo un MP3 normal. |
| D8 | **Validación de dominio** `youtube.com` / `youtu.be` / `music.youtube.com` | Uso local sin auth (doc 03): no convertir al worker en un downloader genérico. |
| D9 | **Fail-soft**: error de yt-dlp/ffmpeg → job `error` con el mensaje real; el export sin música no se toca | YouTube falla a veces (edad, región, bot-check): el usuario ve el error en el diálogo. |
| D10 | Reutilizar `export_document_mp3` para construir la voz, **regenerándola** en cada export con música | El concat de voz toma segundos; garantiza que la mezcla usa el estado actual. |

## 3. Arquitectura de la solución

```
Frontend                          API                        Worker
/editar-audio                     POST /documents/{id}/export     run_export_musica
  pegar URL ────────────────▶      body { musica_url,        ├─ valida audio completo
  volumen (dB)                     musica_volumen_db }       ├─ export_document_mp3 → voz.mp3
  "Crear y descargar"              ├─ valida URL YouTube     ├─ pista_fondo(url)   → música.mp3
                                   └─ crea Export(mp3m)      │    yt-dlp (cache) + concat
  diálogo por etapas ◀──── GET /api/jobs/{id} (polling)      ├─ mezclar_con_musica (ducking+bucle)
  descarga auto ◀──── GET /api/exports/{id}/download         └─ Export(mp3m) done
```

**Job `run_export_musica`** (nuevo, registrado en arq): detalle =
`{export_id, musica_url, musica_volumen_db, etapa}` donde `etapa` ∈
`descargando_musica | mezclando` — el diálogo del frontend la muestra en vivo.

**Filtro de mezcla** (voz = input 0, música = input 1):

```
[0:a]aformat=44100/stereo[voz];
[1:a]aformat=44100/stereo, volume=<db>dB, afade in 3s[mus];
[mus][voz]sidechaincompress=threshold=0.03:ratio=2.5:attack=200:release=1400[d0];
[d0]afade out (dur-6s, 6s)[duck];
[voz][duck]amix=duration=first:normalize=0, alimiter=0.95[a]
```

## 4. Fases de implementación

### Fase 1 — Worker (backend)
- [x] `backend/wispertext/worker/musica.py`:
  `es_url_youtube()`, `pista_fondo()` (yt-dlp + cache + uniformar + concat),
  `mezclar_con_musica()` (filtro ducking + bucle + fades).
- [x] `jobs.py`: `run_export_musica` + helper `_validar_audio_completo`
  compartido con `run_export` + etapas en `job.detalle`.
- [x] `worker/main.py`: registrar la función en arq.
- [x] `requirements.txt`: `yt-dlp>=2026.8`.
- [x] Test unitario: validación de URL y construcción del filtro.

### Fase 2 — API
- [x] `ExportIn`: `musica_url: str | None`, `musica_volumen_db: float = -15`.
- [x] `POST /documents/{id}/export`: si trae `musica_url` → job `export_musica`
  + Export `mp3m`; 400 si la URL no es de YouTube.
- [x] Descarga: nombre de archivo `«título» vN (con música).mp3` para `mp3m`.

### Fase 3 — Frontend
- [x] `app/editar-audio/page.tsx`: página completa (doc base, URL, volumen,
  crear, historial). Suspense por `useSearchParams`.
- [x] `useAudioExport` generalizado: acepta música y muestra la etapa del job.
- [x] `api.ts`: `startExportMusic()`.
- [x] Botón **"Editar audio"** en el menú ⋯ de la tarjeta y en el PlayerPanel
  del lector.

### Fase 4 — Docs, build y pruebas
- [x] Este documento.
- [x] Rebuild de api + worker + frontend; smoke test E2E con URL real.
- [x] Commit + push.

## 5. Riesgos y mitigaciones

- **YouTube bloquea desde el contenedor** (bot-check/edad): el error llega al
  diálogo; alternativa manual = colocar el archivo en el cache
  (`/data/media/music/<sha16>/pista.mp3`). No bloquea nada más.
- **Playlists enormes**: tope 30 pistas (D6).
- **Descargas largas**: `yt-dlp` con timeout 30 min; el job tiene el
  `job_timeout` de 12 h del worker.
- **Espacio**: música cacheada en volumen `media` (MP3 160k ≈ 1.2 MB/min).
- **Calidad de audio**: doble re-encode de la música (bestaudio→mp3→mix) es
  imperceptible a −15 dB bajo la voz.
