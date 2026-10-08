"""Cliente Bonsai (LLM local, OpenAI-compatible) — SIEMPRE fail-soft (ADR-003).

Cualquier error (servicio apagado, timeout, JSON inválido) devuelve None y el
llamante sigue por el camino determinista conservador.
"""

import json
import logging
import re

import httpx

from wispertext.config import get_settings

log = logging.getLogger("wispertext.bonsai")

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> dict | None:
    m = _JSON_RE.search(raw)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def bonsai_formula(texto_lineal: str) -> dict | None:
    """Reconstruye una ecuación extraída lineal de un PDF.

    Devuelve {"latex": "...", "hablado": "..."} o None (fail-soft). El LaTeX
    alimenta el render KaTeX del lector; "hablado" es la lectura en español
    para el TTS (patrón del pipeline texto_voz, Etapa 2).
    """
    settings = get_settings()
    if not settings.bonsai_enabled:
        return None
    prompt = (
        "La siguiente línea viene de extraer un PDF científico y la notación "
        "matemática quedó aplastada a texto lineal. Reconstruye la ecuación. "
        "Responde SOLO JSON con dos claves: \"latex\" (LaTeX correcto y "
        "completo, sin delimitadores $) y \"hablado\" (cómo se lee en voz alta "
        "en español, natural y completo). Si es irreconocible, usa "
        '{"latex": "", "hablado": ""}.\n\n'
        f"Línea:\n---\n{texto_lineal[:500]}\n---"
    )
    try:
        resp = httpx.post(
            f"{settings.bonsai_base_url.rstrip('/')}/chat/completions",
            json={
                "model": settings.bonsai_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 500,
            },
            timeout=settings.bonsai_formula_timeout_s,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        parsed = _extract_json(raw)
        if not parsed:
            return None
        latex = (parsed.get("latex") or "").strip()
        hablado = (parsed.get("hablado") or "").strip()
        if not latex and not hablado:
            return None
        return {"latex": latex, "hablado": hablado}
    except Exception as exc:  # noqa: BLE001 — fail-soft es el contrato
        log.warning("Bonsai formula falló (%s); sigo sin IA", exc)
        return None


def bonsai_is_editorial(texto: str, contexto: str = "") -> bool | None:
    """Clasifica un bloque dudoso como editorial. None = no se pudo decidir."""
    settings = get_settings()
    if not settings.bonsai_enabled:
        return None
    prompt = (
        "Eres un clasificador para un conversor PDF→audiolibro. Decide si el "
        "siguiente bloque de un PDF es contenido EDITORIAL (créditos, ISBN, "
        "copyright, notas legales, ficha bibliográfica, dedicatoria) que debe "
        "SALTARSE, o CONTENIDO que debe leerse. Responde SOLO JSON: "
        '{"editorial": true|false, "motivo": "texto breve"}\n\n'
        f"Contexto (ubicación en el documento): {contexto or 'desconocida'}\n"
        f"Bloque:\n---\n{texto[:800]}\n---"
    )
    try:
        resp = httpx.post(
            f"{settings.bonsai_base_url.rstrip('/')}/chat/completions",
            json={
                "model": settings.bonsai_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 120,
            },
            timeout=settings.bonsai_timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        parsed = _extract_json(raw)
        if parsed and isinstance(parsed.get("editorial"), bool):
            return parsed["editorial"]
        return None
    except Exception as exc:  # noqa: BLE001 — fail-soft es el contrato
        log.warning("Bonsai no disponible (%s); sigo determinista", exc)
        return None


def bonsai_translate(texto: str, destino: str) -> str | None:
    """Traducción asistida opcional (ADR-008). None = usar camino Argos."""
    settings = get_settings()
    if not settings.bonsai_enabled:
        return None
    prompt = (
        f"Traduce al {destino} para ser leído en voz alta. Devuelve SOLO la "
        f"traducción, sin comentarios ni comillas:\n\n{texto[:3000]}"
    )
    try:
        resp = httpx.post(
            f"{settings.bonsai_base_url.rstrip('/')}/chat/completions",
            json={
                "model": settings.bonsai_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=settings.bonsai_timeout_s * 3,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip() or None
    except Exception as exc:  # noqa: BLE001
        log.warning("Bonsai translate falló (%s)", exc)
        return None
