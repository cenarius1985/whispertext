"""Export de audiolibro: concat de MP3 por párrafo con pausas (RF-16)."""

import logging
import uuid
from pathlib import Path

from wispertext.config import get_settings
from wispertext.worker.tts import _run

log = logging.getLogger("wispertext.exporter")


class ExportError(RuntimeError):
    pass


def _silence_mp3(path: Path, seconds: float) -> None:
    res = _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=22050:cl=mono",
            "-t",
            f"{seconds:.2f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            get_settings().tts_bitrate,
            str(path),
        ]
    )
    if res.returncode != 0:
        raise ExportError(f"silencio: {res.stderr[-300:]}")


def export_document_mp3(document, ordered_audio_paths: list[str], out_dir: Path) -> tuple[Path, float]:
    """Concatena los MP3 (orden de índice) intercalando pausas.

    Devuelve (ruta_final, duracion_total_seg). Requiere todos los párrafos
    con audio listo; el llamante valida antes.
    """
    settings = get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f"tmp_{uuid.uuid4().hex[:8]}"
    tmp.mkdir()

    silence = tmp / "silence.mp3"
    _silence_mp3(silence, settings.export_pause_ms / 1000.0)

    lines: list[str] = []
    for i, p in enumerate(ordered_audio_paths):
        if i > 0:
            lines.append(f"file '{silence.as_posix()}'")
        lines.append(f"file '{Path(p).as_posix()}'")
    concat = tmp / "list.txt"
    concat.write_text("\n".join(lines), encoding="utf-8")

    final = out_dir / f"{document.id}_v{document.version_actual}.mp3"
    res = _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-c:a",
            "libmp3lame",
            "-b:a",
            settings.tts_bitrate,
            "-ar",
            "22050",
            "-ac",
            "1",
            str(final),
        ]
    )
    shutil_lite = [f for f in tmp.iterdir()]
    if res.returncode != 0 or not final.exists():
        raise ExportError(f"concat: {res.stderr[-400:]}")
    for f in shutil_lite:
        f.unlink(missing_ok=True)
    tmp.rmdir()

    res = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(final),
        ]
    )
    try:
        dur = float(res.stdout.strip())
    except ValueError:
        dur = 0.0
    return final, dur
