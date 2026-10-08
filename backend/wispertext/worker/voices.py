"""Descarga idempotente de voces Piper desde HuggingFace (primera ejecución)."""

import logging
from pathlib import Path

import httpx

from wispertext.config import get_settings
from wispertext.db import parse_voice_clave

log = logging.getLogger("wispertext.voices")

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def _urls(clave: str) -> list[tuple[str, str]]:
    _nombre, region, calidad, idioma = parse_voice_clave(clave)
    # Las carpetas del repo piper-voices van en minúsculas (case-sensitive en HF)
    folder = f"{idioma}/{region}/{_nombre.lower()}/{calidad}"
    return [
        (f"{BASE}/{folder}/{clave}.onnx", f"{clave}.onnx"),
        (f"{BASE}/{folder}/{clave}.onnx.json", f"{clave}.onnx.json"),
    ]


def ensure_voices_downloaded() -> None:
    settings = get_settings()
    piper_dir = Path(settings.models_dir) / "piper"
    piper_dir.mkdir(parents=True, exist_ok=True)
    for clave in settings.voice_claves:
        missing = [
            (url, dest)
            for url, dest in _urls(clave)
            if not (piper_dir / dest).exists()
        ]
        if not missing:
            log.info("voz %s lista", clave)
            continue
        for url, dest in missing:
            log.info("descargando %s → %s", url, dest)
            with httpx.stream("GET", url, follow_redirects=True, timeout=300) as resp:
                resp.raise_for_status()
                tmp = piper_dir / f"{dest}.part"
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_bytes(1 << 20):
                        fh.write(chunk)
                tmp.rename(piper_dir / dest)
