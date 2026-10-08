#!/usr/bin/env python3
"""Coordinador de WISPERTEXT — deja todo operativo y abre la app.

Qué hace, en orden:
  1. Genera .env con claves dinámicas (password de Postgres aleatorio y
     puertos libres detectados: API desde 8000, frontend desde 3000).
  2. Descarga modelos (reanudables, se saltan si ya existen):
       - Bonsai 8B (GGUF ~2 GB) para reconstruir ecuaciones con IA
         (o usa el que ya esté en backend/bonsai/models/, p.ej. el 27B).
       - Whisper small de faster-whisper (~470 MB) para el módulo STT
         (experimental) en models/whisper/.
  3. Levanta el stack completo con docker compose (build incluido).
  4. Espera la salud de la API y abre la biblioteca en el navegador.

Uso:
    python coordinador.py                 # todo
    python coordinador.py --sin-bonsai    # sin descargar el LLM
    python coordinador.py --sin-whisper   # sin descargar Whisper
    python coordinador.py --regenerar     # sobreescribe un .env existente
    python coordinador.py --no-abrir      # no abre el navegador

Solo usa la librería estándar de Python 3.9+ y `docker` en el PATH.
"""

import argparse
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RAIZ = Path(__file__).resolve().parent

BONSAI_GGUF_URL = (
    "https://huggingface.co/prism-ml/Ternary-Bonsai-8B-gguf/"
    "resolve/main/Ternary-Bonsai-8B-PQ2_0.gguf"
)
BONSAI_GGUF_NAME = "Ternary-Bonsai-8B-PQ2_0.gguf"

WHISPER_BASE = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/"
WHISPER_FILES = ["config.json", "tokenizer.json", "model.bin"]
WHISPER_DIR = RAIZ / "models" / "whisper" / "faster-whisper-small"


def paso(msg: str) -> None:
    print(f"\n==> {msg}")


def puerto_libre(desde: int) -> int:
    for p in range(desde, desde + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return desde


def generar_env(ruta: Path, regenerar: bool) -> None:
    if ruta.exists() and not regenerar:
        print(f"    .env ya existe ({ruta}); se conserva (usa --regenerar para cambiarlo)")
        return
    api = puerto_libre(8000)
    web = puerto_libre(3000)
    contenido = f"""# Generado por coordinador.py — edita a gusto
POSTGRES_USER=whispertext
POSTGRES_PASSWORD={secrets.token_urlsafe(18)}
POSTGRES_DB=whispertext

API_PORT={api}
FRONTEND_PORT={web}
NEXT_PUBLIC_API_URL=http://localhost:{api}

BONSAI_BASE_URL=http://host.docker.internal:4687/v1
BONSAI_MODEL=ternary-bonsai-8b
BONSAI_ENABLED=true

PIPER_VOICE_DEFAULT=es_AR-daniela-high
PIPER_VOICES_EXTRA=en_US-lessac-high,en_US-ryan-high
TTS_FORMAT=mp3
TTS_BITRATE=96k

TESSERACT_LANGS=spa+eng

EXPORT_PAUSE_MS=600
MAX_UPLOAD_MB=200
NORMALIZER_VERSION=v7
CORS_ORIGINS=http://localhost:{web},http://127.0.0.1:{web}
"""
    ruta.write_text(contenido, encoding="utf-8")
    print(f"    .env generado: API en :{api}, web en :{web}, password aleatoria")


def descargar(url: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.stat().st_size > 0:
        print(f"    ya existe: {destino.name} ({destino.stat().st_size // 1048576} MB)")
        return
    tmp = destino.with_suffix(destino.suffix + ".part")
    print(f"    descargando {destino.name} desde {url.split('/')[2]} …")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            leido = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                leido += len(chunk)
                if total:
                    pct = 100 * leido // total
                    print(f"\r    {pct:3d}%  {leido // 1048576}/{total // 1048576} MB", end="")
        print()
        tmp.rename(destino)
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"descarga falló ({destino.name}): {exc}") from exc


def preparar_bonsai() -> None:
    paso("Bonsai (LLM para ecuaciones; opcional y fail-soft)")
    dir_modelos = RAIZ / "backend" / "bonsai" / "models"
    dir_modelos.mkdir(parents=True, exist_ok=True)
    existentes = sorted(dir_modelos.glob("*.gguf"))
    if existentes:
        for gguf in existentes:
            print(f"    encontrado: {gguf.name} ({gguf.stat().st_size // 1048576} MB)")
        print("    (el servicio 'bonsai' del compose usará este modelo por volumen)")
        return
    try:
        descargar(BONSAI_GGUF_URL, dir_modelos / BONSAI_GGUF_NAME)
        print("    Bonsai 8B listo (activar con: docker compose --profile bonsai up -d bonsai)")
    except RuntimeError as exc:
        print(f"    AVISO: {exc}")
        print("    WISPERTEXT funciona igual sin Bonsai (modo determinista);")
        print("    las ecuaciones se muestran como imagen y no se leen.")


def preparar_whisper() -> None:
    paso("Whisper small (STT experimental; opcional)")
    try:
        for nombre in WHISPER_FILES:
            descargar(WHISPER_BASE + nombre, WHISPER_DIR / nombre)
        print(f"    Whisper listo en {WHISPER_DIR}")
    except RuntimeError as exc:
        print(f"    AVISO: {exc} — el módulo STT es experimental y opcional.")


def levantar() -> tuple[str, str]:
    paso("Levantando el stack (docker compose up -d --build)")
    if shutil.which("docker") is None:
        sys.exit("ERROR: docker no está en PATH. Instala Docker Desktop primero.")
    r = subprocess.run(
        ["docker", "compose", "up", "-d", "--build"],
        cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        sys.exit("ERROR: docker compose falló (ver salida arriba)")
    print("    contenedores arriba (la primera vez tarda: builds + voces Piper)")


def esperar_api(api_port: int, timeout_s: int = 240) -> bool:
    print("    esperando a la API", end="")
    url = f"http://localhost:{api_port}/api/health"
    inicio = time.time()
    while time.time() - inicio < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    print(" ✓")
                    return True
        except Exception:  # noqa: BLE001
            pass
        print(".", end="", flush=True)
        time.sleep(3)
    print(" ✗")
    return False


def abrir(web_port: int) -> None:
    import webbrowser

    url = f"http://localhost:{web_port}"
    print(f"\n🎧 Biblioteca: {url}  (¡que lo disfrutes!)\n")
    webbrowser.open(url)


def main() -> int:
    ap = argparse.ArgumentParser(description="Coordinador de WISPERTEXT")
    ap.add_argument("--regenerar", action="store_true", help="sobreescribe el .env existente")
    ap.add_argument("--sin-bonsai", action="store_true", help="no descarga el LLM Bonsai")
    ap.add_argument("--sin-whisper", action="store_true", help="no descarga Whisper")
    ap.add_argument("--no-abrir", action="store_true", help="no abre el navegador")
    args = ap.parse_args()

    print("WISPERTEXT — coordinador de instalación")
    paso("Generando .env")
    generar_env(RAIZ / ".env", args.regenerar)

    if not args.sin_bonsai:
        preparar_bonsai()
    if not args.sin_whisper:
        preparar_whisper()

    levantar()
    env = (RAIZ / ".env").read_text(encoding="utf-8")
    api_port = 8000
    web_port = 3000
    for linea in env.splitlines():
        if linea.startswith("API_PORT="):
            api_port = int(linea.split("=", 1)[1])
        if linea.startswith("FRONTEND_PORT="):
            web_port = int(linea.split("=", 1)[1])

    if esperar_api(api_port):
        if not args.no_abrir:
            abrir(web_port)
        return 0
    print("    la API no respondió a tiempo; revisa: docker compose logs api worker")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
