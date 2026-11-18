"""Cliente Bonsai (LLM local, OpenAI-compatible) — SIEMPRE fail-soft (ADR-003).

Cualquier error (servicio apagado, timeout, JSON inválido) devuelve None y el
llamante sigue por el camino determinista conservador.

Rama local-glm: el "Bonsai" es GLM/Z.AI (endpoint coding del plan coding,
OpenAI-compatible con API key). Si cfg trae api_key se envía el header
Authorization: Bearer; si viene vacío (Bonsai local) no se envía nada.
"""

import json
import logging
import re

import httpx

from wispertext.config import get_settings
from wispertext.llm_runtime import get_llm_config

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


def _headers(cfg: dict) -> dict[str, str]:
    """Headers de la llamada: Authorization Bearer solo si hay api_key."""
    key = cfg.get("api_key")
    return {"Authorization": f"Bearer {key}"} if key else {}


def bonsai_formula(texto_lineal: str) -> dict | None:
    """Reconstruye una ecuación extraída lineal de un PDF.

    Devuelve {"latex": "...", "hablado": "..."} o None (fail-soft). El LaTeX
    alimenta el render KaTeX del lector; "hablado" es la lectura en español
    para el TTS (patrón del pipeline texto_voz, Etapa 2).
    """
    settings = get_settings()  # timeouts operativos
    cfg = get_llm_config()  # base/model/enabled/api_key: Ajustes o .env
    if not cfg["enabled"]:
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
            f"{cfg['base_url']}/chat/completions",
            json={
                "model": cfg["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                # sin razonamiento: con thinking activo quemaba 2000 tokens
                # deliberando y el contenido llegaba vacío (finish_reason: length)
                "thinking": {"type": "disabled"},
                "max_tokens": 2000,
            },
            headers=_headers(cfg),
            timeout=settings.bonsai_formula_timeout_s,
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        raw = msg.get("content") or msg.get("reasoning_content") or ""
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
    """Clasifica si un bloque es editorial (narrativo) o técnico.

    Devuelve True/False, o None si el LLM no está disponible (fail-soft):
    el llamante entonces aplica el camino determinista conservador.
    """
    settings = get_settings()
    cfg = get_llm_config()
    if not cfg["enabled"]:
        return None
    prompt = (
        "Clasifica este bloque de un PDF científico. Responde SOLO JSON con "
        '{"editorial": true|false, "motivo": "texto breve"}\n\n'
        f"Contexto (ubicación en el documento): {contexto or 'desconocida'}\n"
        f"Bloque:\n---\n{texto[:800]}\n---"
    )
    try:
        resp = httpx.post(
            f"{cfg['base_url']}/chat/completions",
            json={
                "model": cfg["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "thinking": {"type": "disabled"},
                "max_tokens": 400,
            },
            headers=_headers(cfg),
            timeout=settings.bonsai_timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        # glm-5.x razona antes de responder: el contenido final puede quedar
        # vacio si max_tokens se gasta en reasoning_content. Extraer JSON de
        # ambos campos y subir el techo de tokens como remedio.
        raw = msg.get("content") or msg.get("reasoning_content") or ""
        parsed = _extract_json(raw)
        if parsed and isinstance(parsed.get("editorial"), bool):
            return parsed["editorial"]
        # reintento unico sin razonamiento (disable thinking via token floor)
        resp2 = httpx.post(
            f"{cfg['base_url']}/chat/completions",
            json={
                "model": cfg["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 800,
            },
            headers=_headers(cfg),
            timeout=settings.bonsai_timeout_s * 2,
        )
        resp2.raise_for_status()
        msg2 = resp2.json()["choices"][0]["message"]
        raw2 = msg2.get("content") or msg2.get("reasoning_content") or ""
        parsed2 = _extract_json(raw2)
        if parsed2 and isinstance(parsed2.get("editorial"), bool):
            return parsed2["editorial"]
        return None
    except Exception as exc:  # noqa: BLE001 — fail-soft es el contrato
        log.warning("Bonsai no disponible (%s); sigo determinista", exc)
        return None


def bonsai_translate(texto: str, destino: str) -> str | None:
    """Traducción asistida opcional (ADR-008). None = usar camino Argos."""
    settings = get_settings()  # timeouts operativos
    cfg = get_llm_config()  # base/model/enabled/api_key: Ajustes o .env
    if not cfg["enabled"]:
        return None
    prompt = (
        f"Traduce al {destino} para ser leído en voz alta. Devuelve SOLO la "
        f"traducción, sin comentarios ni comillas:\n\n{texto[:3000]}"
    )
    try:
        resp = httpx.post(
            f"{cfg['base_url']}/chat/completions",
            json={
                "model": cfg["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            headers=_headers(cfg),
            timeout=settings.bonsai_timeout_s * 3,
        )
        resp.raise_for_status()
        texto_out = resp.json()["choices"][0]["message"]["content"].strip()
        return texto_out or None
    except Exception as exc:  # noqa: BLE001 — fail-soft es el contrato
        log.warning("Bonsai translate falló (%s); camino Argos", exc)
        return None
