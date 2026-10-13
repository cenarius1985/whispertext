"""Síntesis TTS con Piper + cache de audio por hash (ADR-001, ADR-005).

El adapter aísla el motor: synthesize_mp3() es el único punto donde se toca
Piper, para poder enchufar Kokoro/Voicebox después sin tocar el pipeline.
"""

import hashlib
import logging
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from wispertext.config import get_settings
from wispertext.models import AudioAsset, Paragraph, ParagraphAudio

log = logging.getLogger("wispertext.tts")

# contenido audible = al menos una letra o dígito (con acentos es/EN)
_AUDIBLE_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")


class TTSError(RuntimeError):
    pass


def speech_hash(texto_hablado: str) -> str:
    """Hash del texto efectivamente sintetizado (post siglas/traducción)."""
    return hashlib.sha256(texto_hablado.strip().encode("utf-8")).hexdigest()


def audio_cache_key(texto_hablado_hash: str, voz_clave: str, velocidad: float, fmt: str) -> str:
    payload = f"{texto_hablado_hash}|{voz_clave}|{round(velocidad, 2)}|{fmt}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sharded_path(media_audio: Path, key: str, fmt: str) -> Path:
    shard = media_audio / key[:2]
    shard.mkdir(parents=True, exist_ok=True)
    return shard / f"{key}.{fmt}"


def _run(cmd: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
    log.debug("exec: %s", " ".join(cmd[:6]))
    return subprocess.run(
        cmd,
        input=stdin_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
    )


def synthesize_mp3(texto: str, voz_clave: str, velocidad: float, out_path: Path) -> float:
    """Sintetiza con Piper (wav) y transcodifica a MP3. Devuelve duración (s).

    Piper lee el texto por stdin (una línea = una síntesis continua).
    Velocidad > 1 ⇒ length_scale = 1/velocidad (Piper: menor = más rápido).
    """
    settings = get_settings()
    model = Path(settings.models_dir) / "piper" / f"{voz_clave}.onnx"
    if not model.exists():
        raise TTSError(
            f"Voz {voz_clave} no descargada ({model}). Revisa el inicio del worker."
        )
    for binname in ("piper",):
        if shutil.which(binname) is None:
            raise TTSError(f"binario '{binname}' no está en PATH")

    wav_path = out_path.with_suffix(".wav")
    length_scale = 1.0 / max(velocidad, 0.25)
    res = _run(
        [
            "piper",
            "--model",
            str(model),
            "--length-scale",
            f"{length_scale:.3f}",
            "--output_file",
            str(wav_path),
        ],
        stdin_text=texto.replace("\n", " ") + "\n",
    )
    if res.returncode != 0 or not wav_path.exists():
        raise TTSError(f"piper falló: {res.stderr[-400:]}")

    res = _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-ac",
            "1",
            "-ar",
            "22050",
            "-b:a",
            settings.tts_bitrate,
            str(out_path),
        ]
    )
    wav_path.unlink(missing_ok=True)
    if res.returncode != 0 or not out_path.exists():
        raise TTSError(f"ffmpeg falló: {res.stderr[-400:]}")

    res = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(out_path),
        ]
    )
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


async def ensure_audio_for_paragraph(
    session, paragraph: Paragraph, voz_clave: str, velocidad: float
) -> str | None:
    """Garantiza audio del párrafo usando el cache; devuelve la ruta o None.

    Idempotente y seguro ante carreras: la clave única de audio_assets deduplica
    síntesis concurrentes del mismo texto (ADR-005).
    """
    settings = get_settings()
    if paragraph.estado_audio in ("skipped",) or not paragraph.texto_hablado.strip():
        return None

    # Hablado sin contenido audible (solo puntuación/símbolos): Piper genera un
    # WAV vacío y ffmpeg falla con wave.Error. Se salta en lugar de error.
    if not _AUDIBLE_RE.search(paragraph.texto_hablado):
        paragraph.estado_audio = "skipped"
        paragraph.skip_reason = "hablado_vacio"
        await session.commit()
        return None

    th = speech_hash(paragraph.texto_hablado)
    key = audio_cache_key(th, voz_clave, velocidad, settings.tts_format)
    ruta = _sharded_path(Path(settings.media_dir) / "audio", key, settings.tts_format)

    asset = (
        await session.execute(select(AudioAsset).where(AudioAsset.cache_key == key))
    ).scalar_one_or_none()

    if asset is None:
        if not ruta.exists():
            duracion = synthesize_mp3(
                paragraph.texto_hablado, voz_clave, velocidad, ruta
            )
        else:
            duracion = 0.0
        asset = AudioAsset(
            cache_key=key,
            voz_clave=voz_clave,
            velocidad=velocidad,
            formato=settings.tts_format,
            ruta=str(ruta),
            duracion_seg=duracion,
            tamano_bytes=ruta.stat().st_size if ruta.exists() else 0,
        )
        session.add(asset)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            asset = (
                await session.execute(
                    select(AudioAsset).where(AudioAsset.cache_key == key)
                )
            ).scalar_one()

    assoc = (
        await session.execute(
            select(ParagraphAudio).where(
                ParagraphAudio.paragraph_id == paragraph.id,
                ParagraphAudio.audio_id == asset.id,
            )
        )
    ).scalar_one_or_none()
    if assoc is None:
        session.add(ParagraphAudio(paragraph_id=paragraph.id, audio_id=asset.id))
    paragraph.estado_audio = "ready"
    await session.commit()
    return asset.ruta
