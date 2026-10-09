<div align="center">

# 🎧 WISPERTEXT

**Tu biblioteca audible personal: convierte PDF en audio por párrafos y escúchalos en la web.**

<em>Nacido de una necesidad real: concentrarse leyendo documentos largos es difícil — escucharlos, no.</em>

<img src="https://img.shields.io/badge/licencia-MIT-green" alt="Licencia MIT">
<img src="https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose">
<img src="https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white" alt="Python">
<img src="https://img.shields.io/badge/next.js-14-black?logo=next.js" alt="Next.js">
<img src="https://img.shields.io/badge/IA%20local-Piper%20·%20Bonsai-8b5cf6" alt="IA 100% local">

</div>

---

## 🤔 ¿Por qué existe?

Lo creé porque **necesito escuchar en lugar de leer**: documentos técnicos, papers y normas largos que, leídos en pantalla, se me escapaban. Los problemas que resuelve:

- 📄 Los PDF extraídos quedan **rotos para leerlos en voz alta**: acentos partidos (`Metodolog´ıa`), palabras cortadas (`infor-mación`), `T2∗` desarmado, encabezados repetidos, páginas editoriales…
- ⏱️ Procesar de cero un documento que solo cambió un párrafo es un desperdicio → **diff incremental tipo WhatsApp**: solo se sintetiza lo que cambió (99&nbsp;% de ahorro medido en un reemplazo real).
- 🔣 Las **fórmulas matemáticas** se veían como sopa de símbolos → un LLM local las **reconstruye en LaTeX** y hasta **se leen en voz alta**.
- 🖼️ Las **figuras** de los papers (¡incluso las vectoriales!) se recuperan y se muestran en su lugar, con su descripción sonora.

**100&nbsp;% local y sin cuentas**: no hay login, no hay nube, tus documentos no salen de tu máquina.

## ✨ Qué hace

| | |
|---|---|
| 🔊 **Audio por párrafo** con **Piper** (voz por defecto: *Daniela*, español de Argentina; también inglés) | ▶️ **Lector horizontal**: clic en un párrafo → suena y **se resalta** con auto-scroll; reproductor fijo a la derecha |
| 🧹 **Normalizador determinista** para lectura (acentos LaTeX, guiones, `T2∗`, griegas dichas en español, siglas…) | 📚 **Biblioteca**: portadas (subida o página 1 del PDF), búsqueda, título editable, cambiar voz, exportar, eliminar |
| 🧠 **Ecuaciones con IA local (Bonsai, opcional)**: LaTeX → fórmulas reales con KaTeX + lectura hablada; sin LLM queda la imagen fiel | 🔁 **Reemplazo incremental**: sube una versión nueva del PDF y solo se regeneran los párrafos cambiados (cache por hash) |
| 🖼️ **Figuras vectoriales y raster** recuperadas del PDF con su caption, en su posición | 📤 **Export** a un único MP3 con pausas |
| 🔍 OCR (Tesseract spa+eng) para páginas escaneadas | ⚡ Escucha temprana: suenas lo ya sintetizado mientras el resto se genera |

## 🚀 Instalación en 3 pasos

```bash
git clone https://github.com/cenarius1985/whispertext.git
cd whispertext
python coordinador.py
```

Eso es todo. El **coordinador**:

1. Genera el `.env` con **claves dinámicas** (contraseña aleatoria de Postgres y puertos libres detectados automáticamente — se salta los ocupados).
2. Descarga los **modelos** (reanudable, se salta lo existente): Bonsai 8B para las ecuaciones (~2 GB) y Whisper small para el módulo STT experimental (~470 MB).
3. Levanta todo el stack (`docker compose up -d --build`), espera la salud de la API y **abre la biblioteca en tu navegador**.

> Requisitos: **Docker** (Desktop o Engine con compose) y **Python 3.9+**. La primera vez tarda (builds + voces Piper ~300 MB). ¿Red con HuggingFace bloqueada? Mira `docs/07-runbook-primer-arranque.md`.
>
> 🚀 **¿PC con GPU NVIDIA (p. ej. RTX 4060)?** El coordinador la detecta y sirve el Bonsai 27B en VRAM automáticamente; también existe la rama [`gpu`](https://github.com/cenarius1985/whispertext/tree/gpu) afinada para RTX 4060 — detalles en [GPU NVIDIA](#-gpu-nvidia-auto-detectada--rama-gpu-para-rtx-4060).

<details>
<summary><b>🧰 Sin coordinador (a mano)</b></summary>

```bash
cp .env.example .env        # edita puertos y contraseña
docker compose up -d --build
# voces Piper: el worker las descarga solo al arrancar
docker compose logs -f worker
```
</details>

## 🖥️ Requisitos mínimos de hardware

| Perfil | CPU | RAM libre | Disco | Notas |
|---|---|---|---|---|
| **Mínimo** | 4 núcleos x64 | **4 GB** | 6 GB | Stack + voz *Daniela*; sin Bonsai (las ecuaciones se muestran como imagen) |
| **Recomendado** | 6+ núcleos | **8 GB** | 10 GB | + Bonsai 8B en CPU (ecuaciones con LaTeX y lectura) + Whisper |
| **GPU** 🚀 | 4+ núcleos | **8 GB** | 14 GB | **Bonsai 2 27B PTQ1_0 100 % en VRAM** (8 GB bastan) — ver [rama `gpu`](#-gpu-nvidia-auto-detectada), afinada para **RTX 4060** |

### 🚀 GPU NVIDIA (auto-detectada · rama `gpu` para RTX 4060)

¿Tu PC tiene GPU NVIDIA? **El coordinador la detecta solo** (`nvidia-smi`) y en ese caso descarga el **Bonsai 2 27B PTQ1_0** (generación 2, 98.2 % de la inteligencia FP16) y lo sirve **100 % en VRAM** con el binario CUDA del fork PrismML — nada que configurar:

- **PTQ1_0 (~5.7 GB)**: el packing más rápido en tarjetas Ada (RTX 30/40) y el mayor que cabe en 8 GB de VRAM con `-ngl 99`. Medido en una **RTX 4060**: ~30 tok/s.
- Requiere Docker con runtime NVIDIA (Docker Desktop en Windows ya lo incluye).
- ¿VRAM justa por otros programas? Baja `BONSAI_NGL` en el `.env` (p. ej. `60`) para dejar parte de las capas en CPU.

Además existe la **rama [`gpu`](https://github.com/cenarius1985/whispertext/tree/gpu)** del repo — **afinada y verificada específicamente para una RTX 4060 de 8 GB** — donde los defaults ya vienen en modo GPU (Bonsai auto-hospedado activado sin depender de la detección). `main` es **CPU-first**: mismos binarios, pero por defecto apunta a un Bonsai externo en CPU y solo activa el perfil GPU cuando la detecta.

Sin GPU, todo corre en CPU como se describe abajo: sintetizar es más lento que tiempo real en equipos justos; por eso existen la escucha temprana y el cache por hash — solo se sintetiza una vez.

## 🧱 Tecnologías

| Capa | Herramientas |
|---|---|
| Frontend | Next.js 14 (App Router) + Tailwind CSS + KaTeX |
| API | Python 3.11 · FastAPI · SQLAlchemy async · SSE (progreso en vivo) |
| Worker | Python · ARQ (Redis) · PyMuPDF · Tesseract/OCRmyPDF · Piper TTS · ffmpeg |
| Datos | PostgreSQL 16 (párrafos versionados + cache por hash) · Redis 7 |
| IA local (opcional) | Bonsai (`llama-server` PrismML, OpenAI-compatible) · faster-whisper (experimental) |
| Orquestación | Docker Compose (perfiles `completo` y `bonsai`) |

<details>
<summary><b>📁 Estructura del repositorio</b></summary>

```
whispertext/
├── coordinador.py          ← instalación guiada (env + modelos + up + abrir)
├── docker-compose.yml      ← 5 servicios + perfiles (nginx, bonsai)
├── backend/
│   ├── wispertext/
│   │   ├── api/            ← FastAPI: documentos, párrafos, voces, eventos SSE
│   │   └── worker/         ← extracción, limpieza, editorial, diff, TTS, export
│   ├── tests/              ← tests de lógica pura (37)
│   └── bonsai/             ← servicio LLM opcional (tu GGUF va en models/, ignorado por git)
├── frontend/src/           ← biblioteca + lector horizontal + ajustes
├── docs/                   ← PRD, arquitectura, ADRs, modelo de datos, runbooks
└── nginx/                  ← proxy del perfil "completo"
```
</details>

<details>
<summary><b>🧪 Tests</b></summary>

```bash
cd backend && python tests/run_all.py   # 37/37: normalizador, diff, editorial, habla
```
</details>

## 📖 Documentación

Toda la documentación de producto y técnica vive en [`docs/`](docs): PRD completo, arquitectura, decisiones (ADRs), modelo de datos, entorno Docker y runbooks operativos.

## 📜 Licencia

**MIT** — de libre uso: cópialo, adáptalo, mejóralo. Si te sirve, me alegra.

<div align="center">

---

**¡Que lo disfrutéis!** 🎧

<sub>Hecho para escuchar lo que costaba leer.</sub>

</div>
