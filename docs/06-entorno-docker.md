# Entorno Docker — WISPERTEXT

> **Estado: 📝 borrador**
> WISPERTEXT · Compose, servicios, perfiles, volúmenes, variables de
> entorno y presupuestos de recursos. Planificado (sin código aún); el archivo
> definitivo vive en el repo `whispertext` y **el código es la fuente de verdad**.

## Objetivo

Que el stack completo levante con `docker compose up -d` en un PC limitado de
recursos (CPU, sin GPU), con perfiles para ajustar el gasto, y que la
integración con Bonsai externo sea explícita.

## Alcance

Solo despliegue local (docker compose). No hay entornos cloud ni CI/CD en el
alcance del proyecto.

## Contenido

### 1. Servicios y perfiles

| Servicio | Imagen base | Perfil | Rol |
|---|---|---|---|
| `frontend` | `node:20-alpine` (build) → standalone | mínimo, estándar, completo | Next.js 15 + Horizon UI; único puerto publicado (`127.0.0.1:3000`) |
| `api` | `python:3.12-slim` | mínimo (fusionado con worker), estándar, completo | FastAPI: REST + SSE + StaticFiles `/media` |
| `worker` | `python:3.12-slim` + tesseract/ffmpeg | estándar, completo (en mínimo corre dentro de `api`) | ARQ worker: extracción, OCR, limpieza, diff, Piper, Argos, ffmpeg |
| `db` | `postgres:16-alpine` | todos | PostgreSQL: textos + metadatos + FTS |
| `redis` | `redis:7-alpine` | todos | Cola ARQ + pub/sub de progreso |
| `nginx` | `nginx:alpine` | completo | Proxy único punto de entrada + cache de `/media` con `Range` |
| `bonsai` | **externo** (no en este compose) | — | `stack de LLM externa` existente, puerto host 4687 (`ternary-bonsai-8b`) |

- **mínimo**: `frontend` + `api` (con worker embebido) + `db` + `redis` → menos RAM.
- **estándar** (default): todo separado, mejor aislamiento y límites.
- **completo**: + nginx delante (recomendado cuando la biblioteca crezca, por el
  cache de audio con soporte `Range`).

### 2. Volúmenes

| Volumen | Contenido |
|---|---|
| `pgdata` | Datos PostgreSQL |
| `media` | `media/pdfs/` (originales), `media/audio/` (MP3 por hash, sharding 2 niveles), `media/covers/`, `media/images/`, `media/exports/` |
| `models` | `models/piper/` (voces `.onnx` + `.json`), `models/argos/` (paquetes en↔es), futuro `models/whisper/` |
| `watched` (opcional, P2) | Watch folder para auto-ingesta (p. ej. montar `carpeta local de materiales del autor\entrada`) |

### 3. Variables de entorno (`.env.example`, sin secretos)

| Variable | Default propuesto | Nota |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://wispertext:***@db:5432/wispertext` | credenciales locales de desarrollo, viven en `.env` fuera de git |
| `REDIS_URL` | `redis://redis:6379/0` | |
| `BONSAI_BASE_URL` | `http://host.docker.internal:4687/v1` | compose externo `stack de LLM externa` |
| `BONSAI_MODEL` | `ternary-bonsai-8b` | |
| `BONSAI_ENABLED` | `true` | `false` = camino 100 % determinista |
| `PIPER_VOICE_DEFAULT` | `es_AR-daniela-high` | descargada a `models/` en primera ejecución |
| `PIPER_VOICES_EXTRA` | `en_US-amy-high,en_US-lessac-high` | a confirmar al oír |
| `TTS_FORMAT` / `TTS_BITRATE` | `mp3` / `96k` | mono |
| `TESSERACT_LANGS` | `spa,eng` | |
| `EXPORT_PAUSE_MS` | `600` | pausa entre párrafos al exportar |
| `MAX_UPLOAD_MB` | `200` | validación de subida |
| `NORMALIZER_VERSION` | `v1` | parte del hash de cache (ADR-005) |
| `ARGOS_PAIRS` | `en-es` | paquetes a pre-cargar |
| `WATCH_FOLDER_ENABLED` / `WATCH_FOLDER` | `false` / `/watched` | P2 |

### 4. Recursos (presupuesto orientativo, CPU-only)

| Servicio | Memoria estimada |
|---|---|
| `worker` (Piper high + PyMuPDF/OCR) | ~1.5 GB pico (OCR de páginas grandes) |
| `api` | ~300 MB |
| `frontend` (runtime standalone) | ~200 MB |
| `db` | ~300 MB |
| `redis` | ~100 MB |
| **Total estándar** | **~2.5 GB** + lo que ya consuma Bonsai (externo) |

Límites en el compose (`deploy.resources.limits` o `mem_limit`): worker
`cpus: 2`, `memory: 2g`; resto según tabla. Si el PC queda corto: perfil
**mínimo** + voces Piper `medium` (calidad ligeramente menor, mitad de RAM).

### 5. Primera ejecución y operación

1. `cp .env.example .env` y ajustar.
2. `docker compose up -d` → el entrypoint del worker descarga las voces Piper
   listadas a `models/` (una sola vez) y corre migraciones Alembic.
3. Abrir `http://localhost:3000`.
4. Logs: `docker compose logs -f worker` (detalle por párrafo); `logs api` (SSE/HTTP).
5. Actualización: `git pull && docker compose build && docker compose up -d`
   (migraciones idempotentes). Backup: runbook pendiente
   (pendiente).

### 6. Red y publicación de puertos

Solo `frontend` (3000) — y `nginx` (80) en completo — se publican, por defecto
anclados a `127.0.0.1`. `db` y `redis` nunca se publican. Bonsai se alcanza por
`host.docker.internal` desde dentro del compose. Detalle y justificación en
seguridad.

## Ejemplos

Perfil mínimo para un PC muy justo:

```bash
docker compose --profile minimo up -d
# levanta: frontend, api(+worker embebido), db, redis
```

## Checklist de verificación

- [x] Servicios, perfiles, volúmenes y variables definidos (sin secretos).
- [x] Presupuesto de recursos y alternativa liviana documentados.
- [x] Integración con Bonsai externo (`host.docker.internal:4687`) especificada.
- [ ] `docker-compose.yml` real creado en el repo al implementar (fuente de verdad).
- [ ] Runbook de backup y restauración (pendiente, P2).
