# GPU NVIDIA — Bonsai 2 27B 100 % en VRAM (rama `gpu`, integrada a `main`)

> Estado: ✅ verificado en RTX 4060 de 8 GB (2026-10-09)

`main` es **CPU-first**: por defecto apunta a un Bonsai externo y solo activa
el camino GPU cuando la detecta. La rama [`gpu`](https://github.com/cenarius1985/whispertext/tree/gpu)
es la misma código con **defaults GPU-first**, afinada y medida en una
RTX 4060 de 8 GB.

## Cómo funciona

- `coordinador.py` detecta la GPU (`nvidia-smi`) y en ese caso:
  1. descarga **Ternary-Bonsai-2-27B-PTQ1_0** (~5.7 GB) — generación 2,
     98.2 % de la inteligencia FP16,
  2. levanta el stack con `--profile bonsai`: contenedor `llama-server` con el
     **binario CUDA 13.3 del fork PrismML** (el llama.cpp estándar NO corre
     GGUF ternarios) sobre imagen `nvidia/cuda:runtime`,
  3. sirve el modelo **entero en VRAM** (`-ngl 99`), OpenAI-compatible.

## Por qué PTQ1_0 27B en 8 GB

| Criterio | Resultado |
|---|---|
| Memoria | 5.7 GB caben en 8 GB de VRAM; el PQ2_0 (7.2 GB) no |
| Velocidad | En tarjetas **Ada** (RTX 30/40) PTQ1_0 es el packing más rápido (tabla oficial del modelo) |
| Medido en RTX 4060 | ~30 tok/s generación · ~146 tok/s prompt · ecuación LaTeX completa en ~3 s |

El modelo (Qwen3.8-27B ternarizado) usa atención híbrida 75 % lineal → KV cache
mínimo, ideal para VRAM ajustada. El `entrypoint.sh` desactiva el thinking por
defecto (`--reasoning-budget 0` + kwarg del template) para respuestas rápidas
en el pipeline de ecuaciones; `BONSAI_THINKING=1` lo enciende.

## Variables relevantes (`.env`)

| Var | Default main | Uso |
|---|---|---|
| `BONSAI_BASE_URL` | externo `:4687/v1` | con GPU: `http://bonsai:8080/v1` (lo escribe el coordinador) |
| `BONSAI_MODEL` | `ternary-bonsai-8b` | alias del servidor (`ternary-bonsai-2-27b` con GPU) |
| `BONSAI_NGL` | `99` | capas en VRAM; bájalo (p. ej. `60`) si otros apps usan la GPU |
| `BONSAI_THINKING` | `0` | `1` activa razonamiento (mucho más lento) |
| `BONSAI_CTX` | `8192` | contexto del servidor |

> Requiere Docker con runtime NVIDIA (Docker Desktop en Windows ya lo trae).
> El perfil `bonsai` reserva el dispositivo GPU en `docker-compose.yml`.

## Ajuste fino operativo

- **VRAM justa**: baja `BONSAI_NGL` en el `.env` para dejar capas en CPU.
- **Primer request frío**: tras inactividad, el page-in del modelo puede tardar
  >30 s; el segundo baja a segundos. No confundir frío con caído.
- También puedes cambiar el endpoint/modelo **en caliente** desde Ajustes (ver
  [10-llm-configurable.md](10-llm-configurable.md)).
