"""Música de fondo desde YouTube para los exports (docs/11, RF-MUS-01).

Pipeline: yt-dlp descarga SOLO audio (cacheado por hash de URL) → pistas
uniformes 44.1 kHz estéreo MP3 → concat (playlist) → mezcla bajo la
narración con ducking (la música baja sola cuando habla la voz y recupera
nivel en las pausas). Si la música no cubre la duración total se repite
en bucle (-stream_loop -1 + amix duration=first).

La receta de mezcla viene probada de Presentacion-iHealth (src/musica.py).
"""

import hashlib
import logging
import re
import shutil
import subprocess
import uuid
from pathlib import Path

log = logging.getLogger("wispertext.musica")

MAX_PISTAS = 30  # tope de sanidad para playlists (docs/11 D6)
FADE_IN, FADE_OUT = 3.0, 6.0
DUCK = "threshold=0.03:ratio=2.5:attack=200:release=1400"
_YT_RE = re.compile(r"^https?://(www\.|music\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)


class MusicaError(RuntimeError):
    pass


def es_url_youtube(url: str) -> bool:
    return bool(_YT_RE.match((url or "").strip()))


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )


def filtro_mezcla(dur_voz: float, volumen_db: float) -> str:
    """Cadena ffmpeg: voz (0) + música (1) con ducking, bucle y fades.

    Con -stream_loop -1 la música es infinita: amix duration=first corta
    donde termina la voz y -t dur vuelve a acotarlo por si acaso.
    """
    st = max(dur_voz - FADE_OUT, 0)
    return (
        "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[voz];"
        "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,"
        f"volume={volumen_db:.1f}dB,afade=t=in:d={FADE_IN}[mus];"
        f"[mus][voz]sidechaincompress={DUCK}[d0];"
        f"[d0]afade=t=out:st={st:.1f}:d={FADE_OUT}[duck];"
        "[voz][duck]amix=inputs=2:duration=first:normalize=0,"
        "alimiter=limit=0.95[a]"
    )


def _duracion(path: Path) -> float:
    res = _run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        timeout=120,
    )
    try:
        return float(res.stdout.strip())
    except ValueError:
        raise MusicaError(f"no se pudo leer la duración de {path.name}") from None


def _uniformar(p: Path, dest_dir: Path) -> Path:
    """Re-encode a MP3 44.1 kHz estéreo 160k: parámetros idénticos entre
    pistas para que el concat demuxer funcione con -c copy."""
    dest = dest_dir / f"u{p.stem}.mp3"
    res = _run(
        [
            "ffmpeg", "-y", "-i", str(p),
            "-ar", "44100", "-ac", "2",
            "-c:a", "libmp3lame", "-b:a", "160k", str(dest),
        ],
        timeout=600,
    )
    if res.returncode != 0 or not dest.exists():
        raise MusicaError(f"uniformar {p.name}: {res.stderr[-300:]}")
    return dest


def pista_fondo(url: str, media_dir: Path) -> Path:
    """Descarga la música (con cache por hash de URL) y devuelve UN mp3:
    la canción única o la playlist entera concatenada en orden.

    yt-dlp baja bestaudio nativo (opus/m4a); la conversion a MP3 uniforme
    la hacemos nosotros con ffmpeg (un solo re-encode extra).
    """
    url = url.strip()
    clave = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    cache_dir = media_dir / "music" / clave
    final = cache_dir / "pista.mp3"
    if final.exists():
        log.info("música en cache: %s", final)
        return final

    if shutil.which("yt-dlp") is None:
        raise MusicaError("yt-dlp no está instalado en el worker (rebuild imagen)")

    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / f"tmp_{uuid.uuid4().hex[:8]}"
    tmp.mkdir()
    try:
        log.info("descargando música: %s", url)
        res = _run(
            [
                "yt-dlp",
                "-f", "bestaudio", "-x",
                "--playlist-end", str(MAX_PISTAS),
                "--no-progress", "--no-warnings", "--ignore-config",
                "-o", str(tmp / "%(playlist_index)03d-%(id)s.%(ext)s"),
                url,
            ]
        )
        if res.returncode != 0:
            # error típico: edad/región/bot-check — el mensaje llega al diálogo
            raise MusicaError(f"yt-dlp falló: {(res.stderr or res.stdout)[-500:]}")
        crudos = sorted(p for p in tmp.iterdir() if p.suffix != ".txt")
        if not crudos:
            raise MusicaError("yt-dlp no descargó ninguna pista (¿URL válida?)")

        pistas = [_uniformar(p, tmp) for p in crudos]
        if len(pistas) == 1:
            pistas[0].replace(final)
        else:
            lst = tmp / "list.txt"
            lst.write_text(
                "\n".join(f"file '{p.as_posix()}'" for p in pistas), encoding="utf-8"
            )
            res = _run(
                [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c:a", "copy", str(final),
                ],
                timeout=600,
            )
            if res.returncode != 0 or not final.exists():
                raise MusicaError(f"concat música: {res.stderr[-300:]}")
        log.info("música lista (%d pista(s), %.1f min): %s",
                 len(pistas), _duracion(final) / 60, final.name)
        return final
    finally:
        # rmdir() no acepta missing_ok: limpieza tolerante a fallos previos
        shutil.rmtree(tmp, ignore_errors=True)


def mezclar_con_musica(
    narracion: Path, pista: Path, out_path: Path, volumen_db: float, bitrate: str
) -> Path:
    """Narración + música ducked en bucle → MP3. Devuelve out_path."""
    dur = _duracion(narracion)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(narracion),
        "-stream_loop", "-1", "-i", str(pista),
        "-filter_complex", filtro_mezcla(dur, volumen_db),
        "-map", "[a]",
        "-t", f"{dur:.2f}",
        "-c:a", "libmp3lame", "-b:a", bitrate, "-ar", "44100", "-ac", "2",
        str(out_path),
    ]
    res = _run(cmd, timeout=3600)
    if res.returncode != 0 or not out_path.exists():
        raise MusicaError(f"mezcla ffmpeg: {res.stderr[-400:]}")
    return out_path
