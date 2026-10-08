# Runbook — Primer arranque y provisión de voces (red con HuggingFace bloqueada)

> **Estado: ✅ verificado** · Probado en este PC el 2026-10-08 con el stack completo

## Objetivo

Levant WISPERTEXT desde cero y garantizar las voces Piper aunque
`huggingface.co` no sea alcanzable desde la red (este PC lo tiene bloqueado:
`Connection refused/timeout`, mientras PyPI y GitHub sí funcionan).

## Alcance

- Arranque estándar del stack (`docker compose up -d`).
- Descarga automática de voces (red sin restricciones) y provisión manual
  (esta red) vía RPM de OpenMandriva + `docker compose cp`.
- Verificación de humo (piper sintetiza + API responde).

## Contenido — Pasos

### 1. Arranque estándar

```bash
cd whispertext  # (la carpeta donde clonaste el repo)
cp .env.example .env       # ajustar puertos si 8000/3000 están ocupados:
                           #   API_PORT, FRONTEND_PORT, NEXT_PUBLIC_API_URL
docker compose up -d --build
```

- El worker descarga voces de HF al arrancar (idempotente). Si HF está
  bloqueado, registra el error y sigue (fail-soft); la síntesis por párrafo
  marcará error hasta proveer las voces manualmente (paso 3).
- Verificar: `docker compose ps` (db/redis healthy) y
  `curl http://localhost:$API_PORT/api/health` → `{"status":"ok"}`.

### 2. Puertos ocupados en el host (caso real de este PC)

8000 y 3000 suelen estar tomados. En `.env`:

```
API_PORT=8001
FRONTEND_PORT=3100
NEXT_PUBLIC_API_URL=http://localhost:8001
```

`NEXT_PUBLIC_API_URL` se hornea en el build del frontend: si cambia,
`docker compose build frontend` y `up -d frontend`.

### 3. Voces sin HuggingFace (red bloqueada) — verificado 2026-10-08

Las voces Piper también se empaquetan como RPM de OpenMandriva
(rpmfind.net, alcanzable desde esta red). Procedimiento probado para
`es_AR-daniela-high`:

```bash
# 3.1 descargar RPM (105 MB; lento ~250 KB/s, reanudar con -C - hasta HTTP 416)
curl -L -C - -o /tmp/daniela.rpm \
  "http://rpmfind.net/linux/openmandriva/cooker/repository/x86_64/main/release/piper-voice-es_AR-daniela-2023.09.23-1-omv2590.noarch.rpm"

# 3.2 extraer onnx + json (pip install rpmfile en el Python local)
python - <<'EOF'
import rpmfile, pathlib, tempfile
tmp = pathlib.Path(tempfile.gettempdir())
dest = tmp / "piper_voz"; dest.mkdir(exist_ok=True)
with rpmfile.open(str(tmp / "daniela.rpm")) as rpm:
    for m in rpm.getmembers():
        name = pathlib.PurePosixPath(m.name).name
        if name.startswith("es_AR-daniela"):
            with rpm.extractfile(m) as s, open(dest / name, "wb") as fh:
                fh.write(s.read())
            print("extraído:", name)
EOF

# 3.3 copiar al volumen del worker (¡persiste entre reinicios!)
cd <repo>
docker compose cp /tmp/piper_voz/es_AR-daniela-high.onnx worker:/data/models/piper/
docker compose cp /tmp/piper_voz/es_AR-daniela-high.onnx.json worker:/data/models/piper/

# 3.4 smoke de síntesis dentro del worker
docker compose exec -T worker sh -c \
  'echo "prueba de voz" | piper --model /data/models/piper/es_AR-daniela-high.onnx --output_file /tmp/p.wav && \
   ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /tmp/p.wav'
```

Notas:

- **Con red móvil (o cualquier red sin el bloqueo), HF es alcanzable y el
  worker descarga las voces solo al arrancar** — el paso 3 solo aplica en la
  red del trabajo. Verificado en ambas el 2026-10-08.
- El RPM contiene los DOS archivos (`onnx` 114 MB + `onnx.json` 7 KB); si la
  extracción lista solo el onnx, el RPM está truncado (reanudar descarga).
- Otros directorios de voces existen en el mismo repo RPM (en_GB, de_DE, …).
- El listado de paquetes:
  `http://rpmfind.net/linux/openmandriva/cooker/repository/x86_64/main/release/` →
  filtrar `piper-voice-*`.
- Variantes válidas por voz (verificar antes de configurar
  `PIPER_VOICES_EXTRA`): `amy` NO tiene high (solo low/medium);
  `lessac` y `ryan` sí. Decisión del usuario: **solo voces high**
  (`es_AR-daniela-high`, `en_US-lessac-high`, `en_US-ryan-high`).

### 4. Verificación funcional completa (1 minuto)

```bash
# voces sembradas en BD
curl -s http://localhost:8001/api/voices
# subir un PDF pequeño y ver estados pending→extracting→cleaning→synthesizing→ready
curl -s -X POST -F "archivo=@documento.pdf" http://localhost:8001/api/documents
```

## Ejemplos

Estado final verificado en esta PC: 5 servicios Up, voz Daniela operativa,
ingesta completa de un PDF de 14 páginas → 142 párrafos + 140 MP3 (11 MB),
export unido de 26 min de audio.

## Checklist de verificación

- [x] Pasos ejecutados y verificados en el equipo (2026-10-08).
- [x] Fail-soft de la descarga de voces documentado.
- [x] Comandos reproducibles textualmente.
- [ ] Confirmar en futuras ejecuciones si HF vuelve a estar accesible
      (entonces basta el paso 1).
